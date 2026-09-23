#!/usr/bin/env bash
# Install, remove or run the daily refresh-and-publish job.
#
# The job has to run after the US close *and* after the publishers post. Not
# at the closing bell: State Street's holdings and NAV files land in the
# evening, and Treasury sometimes does not post the par curve until early
# evening ET. A job that fires at 16:00 ET builds a page entirely from the
# previous session and reports itself perfectly healthy while doing it.
#
# launchd's StartCalendarInterval fires in LOCAL time, not ET. This machine is
# in London, so a naive "18:30" fired at 13:30 New York -- the middle of the
# session -- and the completed-session guard correctly served the previous
# day's close, leaving the page permanently a day behind.
#
# 23:30 local is the hour that works all year from London, because it is never
# earlier than 18:30 ET at any point in either country's DST cycle:
#
#   BST + EDT (now)          offset 5h   23:30 local = 18:30 ET
#   GMT + EDT (late Oct)     offset 4h   23:30 local = 19:30 ET
#   GMT + EST (from Nov)     offset 5h   23:30 local = 18:30 ET
#
# Override for another timezone with SCHEDULE_HOUR / SCHEDULE_MINUTE.
set -euo pipefail

SCHEDULE_HOUR="${SCHEDULE_HOUR:-23}"
SCHEDULE_MINUTE="${SCHEDULE_MINUTE:-30}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.market-recap.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$REPO/data/logs"
STATUS_FILE="$LOG_DIR/last-run.json"
# The log is append-only across every run. Capped so a nightly job cannot
# quietly fill a disk over a year.
LOG_MAX_BYTES=$((2 * 1024 * 1024))
# Credentials live outside the repository, so no clone or backup of this
# project can carry them and no `git add -A` can stage them.
ENV_FILE="${MARKET_RECAP_ENV:-$HOME/.config/market-recap/env}"

usage() { echo "usage: $0 {install|uninstall|status|run|check}" >&2; exit 2; }

rotate_log() {
  local log="$LOG_DIR/refresh.log"
  [ -f "$log" ] || return 0
  local size
  size="$(stat -f '%z' "$log" 2>/dev/null || stat -c '%s' "$log")"
  [ "$size" -gt "$LOG_MAX_BYTES" ] && mv -f "$log" "$log.1"
  return 0
}

# Record how the run ended, so "did it work last night?" is one command rather
# than a scroll through an append-only log.
record() {
  local outcome="$1" detail="$2" started="$3"
  printf '{"finished_at":"%s","outcome":"%s","detail":"%s","seconds":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$outcome" "$detail" "$(( $(date +%s) - started ))" \
    > "$STATUS_FILE"
}

load_env() {
  [ -f "$ENV_FILE" ] || return 0
  # Refuse a credentials file other users can read. An unattended job is
  # exactly where a 644 token sits unnoticed for months.
  local mode
  mode="$(stat -f '%OLp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")"
  case "$mode" in
    600|400) ;;
    *) echo "refusing to read $ENV_FILE: mode $mode, want 600 (chmod 600 '$ENV_FILE')" >&2; return 1 ;;
  esac
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}

# launchd starts a job with a minimal PATH that has no node and no python.
# Resolving them here rather than inheriting a shell's PATH is the difference
# between a job that runs nightly and one that silently never has.
setup_path() {
  for dir in /opt/homebrew/bin /usr/local/bin "$HOME/.pyenv/shims"; do
    [ -d "$dir" ] && PATH="$dir:$PATH"
  done
  export PATH
}

wrangler_bin() {
  if [ -x "$REPO/node_modules/.bin/wrangler" ]; then
    echo "$REPO/node_modules/.bin/wrangler"
  else
    echo ""
  fi
}

case "${1:-}" in
  install)
    mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
    cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/schedule.sh</string>
    <string>run</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
$(for day in 1 2 3 4 5; do
  printf '    <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>%s</integer><key>Minute</key><integer>%s</integer></dict>\n' \
    "$day" "$SCHEDULE_HOUR" "$SCHEDULE_MINUTE"
done)
  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/refresh.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/refresh.log</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST_EOF
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    # Report the New York equivalent, since "after the publishers post" is an
    # ET constraint and the local clock is what launchd actually fires on.
    # Converting means resolving the local time to an instant first; simply
    # reformatting "23:30" under TZ=America/New_York prints 23:30 back.
    stamp="$(date -j -f '%Y-%m-%d %H:%M' "$(date +%Y-%m-%d) $SCHEDULE_HOUR:$SCHEDULE_MINUTE" +%s 2>/dev/null || echo "")"
    if [ -n "$stamp" ]; then
      echo "installed $LABEL (weekdays $SCHEDULE_HOUR:$SCHEDULE_MINUTE $(date +%Z)" \
           "= $(TZ=America/New_York date -r "$stamp" '+%H:%M %Z') New York)"
    else
      echo "installed $LABEL (weekdays $SCHEDULE_HOUR:$SCHEDULE_MINUTE local)"
    fi
    echo "log:   $LOG_DIR/refresh.log"
    echo "creds: $ENV_FILE"
    "$0" check
    ;;

  uninstall)
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    ;;

  status)
    if launchctl list | grep -qF "$LABEL"; then
      # 'launchctl list' prints exit 0 for a job that has never run, which reads
      # as success. 'print' separates "never ran" from "ran and exited 0".
      info="$(launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null)"
      runs="$(awk -F' = ' '/^\truns = /{print $2}' <<<"$info")"
      last="$(awk -F' = ' '/^\tlast exit code = /{print $2}' <<<"$info")"
      echo "launchd:  loaded (runs ${runs:-?}, last exit ${last:-?})"
    else
      echo "launchd:  NOT LOADED -- run 'make schedule'"
    fi
    if [ -f "$STATUS_FILE" ]; then
      echo "last run: $(cat "$STATUS_FILE")"
    else
      echo "last run: none recorded yet"
    fi
    echo "next:     weekdays $SCHEDULE_HOUR:$SCHEDULE_MINUTE $(date +%Z)"
    ;;

  check)
    # Say what the next scheduled run will actually be able to do, now,
    # rather than letting it discover the answer overnight into a log file.
    setup_path
    load_env || exit 1
    ok=0
    command -v python3 >/dev/null && echo "  python3   $(command -v python3)" || { echo "  python3   MISSING"; ok=1; }
    command -v node    >/dev/null && echo "  node      $(command -v node)"    || { echo "  node      MISSING"; ok=1; }
    bin="$(wrangler_bin)"
    [ -n "$bin" ] && echo "  wrangler  $bin" || { echo "  wrangler  MISSING (run: npm install)"; ok=1; }
    if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
      echo "  token     present (${#CLOUDFLARE_API_TOKEN} chars)"
    else
      echo "  token     ABSENT -- the job will refresh and validate but not deploy"
      ok=1
    fi
    [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ] && echo "  account   set" || echo "  account   unset (fine for a single-account token)"
    exit $ok
    ;;

  run)
    cd "$REPO"
    setup_path
    mkdir -p "$LOG_DIR"
    rotate_log
    started=$(date +%s)
    # Any unexpected exit is recorded too, so a crash is distinguishable from
    # a run that never started.
    trap 'record failed "job exited unexpectedly" "$started"' ERR
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) refresh starting ==="
    load_env || true

    # --strict: a scheduled run has nobody reading the output, so a warning is
    # a failure. An unattended job that exits 0 on a degraded build is how a
    # stale page stays up for a week.
    PYTHONPATH=src python3 -m market_recap.cli refresh --history 10y --strict

    bin="$(wrangler_bin)"
    if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
      echo "CLOUDFLARE_API_TOKEN not set; built and validated but not deployed"
      echo "  put it in $ENV_FILE (chmod 600) as CLOUDFLARE_API_TOKEN=..."
      record built-not-deployed "no CLOUDFLARE_API_TOKEN" "$started"
      exit 0
    fi
    if [ -z "$bin" ]; then
      echo "wrangler not installed; run 'npm install' in $REPO" >&2
      record failed "wrangler missing" "$started"
      exit 1
    fi
    # Only a build that passed --strict is published. Deploying first and
    # validating afterwards would put the bad page in front of people and then
    # tell a log file about it.
    "$bin" pages deploy dist --project-name market-recap --branch main --commit-dirty=true
    record deployed "$(PYTHONPATH=src python3 -c 'import json;print(json.load(open("artifacts/manifest.json"))["as_of"])' 2>/dev/null || echo unknown)" "$started"
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) done ==="
    ;;

  *) usage ;;
esac
