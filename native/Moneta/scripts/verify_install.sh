#!/bin/bash
set -euo pipefail
APP_PATH="${1:-/Applications/Moneta.app}"
/bin/test -x "$APP_PATH/Contents/MacOS/Moneta"
/usr/bin/plutil -lint "$APP_PATH/Contents/Info.plist" >/dev/null
/usr/bin/codesign --verify --deep --strict "$APP_PATH"
/usr/bin/curl -fsS --max-time 10 "http://127.0.0.1:8765/api/analytics?range=12" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["trend"] and d["transactions"] and d["meta"]["selected_month"]'
echo "Moneta install and live API verification passed"
