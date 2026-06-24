#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/PaperMonitor"
USER_APPS="$HOME/Applications"
APP_NAME="Paper Monitor.app"
OLD_APP_NAME="Paper Monitor.app"
APP_SOURCE="$ROOT_DIR/dist/$APP_NAME"
APP_TARGET="$USER_APPS/$APP_NAME"
OLD_APP_TARGET="$USER_APPS/$OLD_APP_NAME"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.local.paper-monitor.app.plist"
OLD_LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.local.paper-monitor.plist"

"$ROOT_DIR/scripts/build_macos_app.sh" >/dev/null

mkdir -p "$APP_SUPPORT" "$USER_APPS" "$HOME/Library/LaunchAgents"
pkill -x "PaperMonitorApp" 2>/dev/null || true
pkill -x "SolidBatteryMonitorApp" 2>/dev/null || true
sleep 1
rm -rf "$APP_TARGET" "$OLD_APP_TARGET"
cp -R "$APP_SOURCE" "$APP_TARGET"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_TARGET" 2>/dev/null || true

rsync -a "$ROOT_DIR/paper_monitor/" "$APP_SUPPORT/paper_monitor/"
CONFIG_SOURCE="$ROOT_DIR/config.json"
if [ ! -f "$CONFIG_SOURCE" ]; then
  CONFIG_SOURCE="$ROOT_DIR/config.example.json"
fi
if [ ! -f "$APP_SUPPORT/config.json" ]; then
  cp "$CONFIG_SOURCE" "$APP_SUPPORT/config.json"
fi
cp "$ROOT_DIR/config.example.json" "$APP_SUPPORT/config.example.json"
cp "$ROOT_DIR/journal_metrics.json" "$APP_SUPPORT/journal_metrics.json"
cp "$ROOT_DIR/README.md" "$APP_SUPPORT/README.md"
if [ -f "$ROOT_DIR/PaperMonitor.command" ]; then
  cp "$ROOT_DIR/PaperMonitor.command" "$APP_SUPPORT/PaperMonitor.command"
  chmod +x "$APP_SUPPORT/PaperMonitor.command"
fi
if [ -f "$ROOT_DIR/PaperMonitorDashboard.command" ]; then
  cp "$ROOT_DIR/PaperMonitorDashboard.command" "$APP_SUPPORT/PaperMonitorDashboard.command"
  chmod +x "$APP_SUPPORT/PaperMonitorDashboard.command"
fi

launchctl bootout "gui/$(id -u)/com.local.paper-monitor" 2>/dev/null || true
rm -f "$OLD_LAUNCH_AGENT"

cat > "$LAUNCH_AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.paper-monitor.app</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>$APP_TARGET</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST

plutil -lint "$LAUNCH_AGENT"
launchctl bootout "gui/$(id -u)/com.local.paper-monitor.app" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT"
open "$APP_TARGET"
rm -rf "$APP_SOURCE"

echo "Installed $APP_TARGET"
