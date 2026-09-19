#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_PATH="${1:-/Applications/Moneta.app}"
SCRATCH_PATH="${MONETA_SCRATCH_PATH:-/Volumes/Media/AutomationStore/project-artifacts/moneta/$(date +%F)/package-build}"
BUILD_DIR="$SCRATCH_PATH"
ICON_WORK="$BUILD_DIR/app-icon"
ICONSET="$ICON_WORK/Moneta.iconset"
if [ -n "${MONETA_BINARY:-}" ] && [ -x "$MONETA_BINARY" ]; then
  BUILT_BINARY="$MONETA_BINARY"
else
  /bin/mkdir -p "$SCRATCH_PATH"
  /usr/bin/swift build --package-path "$ROOT" --scratch-path "$SCRATCH_PATH" -c release
  BUILT_BINARY="$SCRATCH_PATH/release/Moneta"
fi
/bin/mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources" "$ICONSET"
/bin/cp "$BUILT_BINARY" "$APP_PATH/Contents/MacOS/Moneta"
/bin/cp "$ROOT/Resources/Info.plist" "$APP_PATH/Contents/Info.plist"
/bin/chmod 755 "$APP_PATH/Contents/MacOS/Moneta"
/bin/mkdir -p "$ICON_WORK"
/usr/bin/swift "$ROOT/scripts/generate_icon.swift" "$ICON_WORK/Moneta-1024.png"
for spec in "16:icon_16x16.png" "32:icon_16x16@2x.png" "32:icon_32x32.png" "64:icon_32x32@2x.png" "128:icon_128x128.png" "256:icon_128x128@2x.png" "256:icon_256x256.png" "512:icon_256x256@2x.png" "512:icon_512x512.png" "1024:icon_512x512@2x.png"; do
  pixels="${spec%%:*}"; name="${spec#*:}"
  /usr/bin/sips -z "$pixels" "$pixels" "$ICON_WORK/Moneta-1024.png" --out "$ICONSET/$name" >/dev/null
done
/usr/bin/iconutil -c icns "$ICONSET" -o "$APP_PATH/Contents/Resources/Moneta.icns"
/usr/bin/codesign --force --deep --sign - "$APP_PATH"
/usr/bin/touch "$APP_PATH"
echo "$APP_PATH"
