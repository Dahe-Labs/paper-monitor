#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export COPYFILE_DISABLE=1
APP_NAME="Paper Monitor"
PACKAGE_DIR="$ROOT_DIR/macos/PaperMonitorApp"
DIST_DIR="$ROOT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

cd "$PACKAGE_DIR"
python3 "$ROOT_DIR/scripts/generate_app_icons.py"
iconutil -c icns "$PACKAGE_DIR/Assets/AppIcon.iconset" -o "$PACKAGE_DIR/Assets/AppIcon.icns"
swift build -c release

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$PACKAGE_DIR/.build/release/PaperMonitorApp" "$MACOS_DIR/PaperMonitorApp"
cp "$PACKAGE_DIR/Info.plist" "$CONTENTS_DIR/Info.plist"
cp "$PACKAGE_DIR/Assets/AppIcon.icns" "$RESOURCES_DIR/AppIcon.icns"
rsync -a --exclude '__pycache__' --exclude '.DS_Store' --exclude '._*' --exclude '__MACOSX' "$ROOT_DIR/paper_monitor/" "$RESOURCES_DIR/paper_monitor/"
cp "$ROOT_DIR/config.example.json" "$RESOURCES_DIR/config.example.json"
cp "$ROOT_DIR/journal_metrics.json" "$RESOURCES_DIR/journal_metrics.json"
cp "$ROOT_DIR/README.md" "$RESOURCES_DIR/README.md"
find "$APP_DIR" \( -name '._*' -o -name '.DS_Store' -o -name '__MACOSX' \) -prune -exec rm -rf {} +
chmod +x "$MACOS_DIR/PaperMonitorApp"
codesign --force --deep --sign - "$APP_DIR"

echo "$APP_DIR"
