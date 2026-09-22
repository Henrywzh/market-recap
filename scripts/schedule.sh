#!/usr/bin/env bash
# Install or remove the daily refresh as a launchd job.
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

usage() { echo "usage: $0 {install|uninstall|status|run}" >&2; exit 2; }

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
</dict>
</plist>
PLIST_EOF
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "installed $LABEL (weekdays 18:30 local); log: $LOG_DIR/refresh.log"
    ;;
  uninstall)
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    ;;
  status)
    launchctl list | grep -F "$LABEL" || echo "$LABEL is not loaded"
    ;;
  run)
    cd "$REPO"
    mkdir -p "$LOG_DIR"
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) refresh starting ==="
    # --strict: a scheduled run has nobody reading the output, so a warning is
    # a failure. An unattended job that exits 0 on a degraded build is how a
    # stale page stays up for a week.
    PYTHONPATH=src python3 -m market_recap.cli refresh --history 10y --strict
    ;;
  *) usage ;;
esac
