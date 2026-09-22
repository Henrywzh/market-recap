#!/usr/bin/env bash
# Install, remove or run the daily refresh-and-publish job.
#
# 18:30 ET on weekdays. Not at the closing bell: the issuers this dashboard
# reads publish after it. State Street's holdings and NAV files land in the
# evening, and Treasury sometimes does not post the par curve until early
# evening ET, so a job that fires at 16:00 produces a page built entirely from
# the previous session and reports itself perfectly healthy while doing it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.market-recap.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$REPO/data/logs"
# Credentials live outside the repository, so no clone or backup of this
# project can carry them and no `git add -A` can stage them.
ENV_FILE="${MARKET_RECAP_ENV:-$HOME/.config/market-recap/env}"

usage() { echo "usage: $0 {install|uninstall|status|run|check}" >&2; exit 2; }

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
  printf '    <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>\n' "$day"
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
    echo "installed $LABEL (weekdays 18:30 local)"
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
    launchctl list | grep -F "$LABEL" || echo "$LABEL is not loaded"
    ;;

  check)
    # Say what the next scheduled run will actually be able to do, now,
    # rather than letting it discover the answer at 18:30 into a log file.
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
      exit 0
    fi
    if [ -z "$bin" ]; then
      echo "wrangler not installed; run 'npm install' in $REPO" >&2
      exit 1
    fi
    # Only a build that passed --strict is published. Deploying first and
    # validating afterwards would put the bad page in front of people and then
    # tell a log file about it.
    "$bin" pages deploy dist --project-name market-recap --branch main --commit-dirty=true
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) done ==="
    ;;

  *) usage ;;
esac
