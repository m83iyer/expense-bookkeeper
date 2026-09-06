#!/usr/bin/env bash
set -euo pipefail

rm -rf cloud-validation
mkdir -p cloud-validation/demo

python -m compileall -q cli.py scripts dashboard tests
node --check dashboard/static/app.js
python -m pytest tests/ -q --junitxml=cloud-validation/pytest.xml
python scripts/privacy_audit.py . --history --history-ref HEAD --json-out cloud-validation/privacy.json
python -m pip_audit -r requirements.txt --format=json --output=cloud-validation/dependencies.json
python cli.py dashboard-demo --output cloud-validation/demo > cloud-validation/demo-build.json

python - <<'PY'
import json
import os
import platform
import sqlite3
from pathlib import Path

import yaml

from dashboard.server import Dashboard

root = Path("cloud-validation")
demo = json.loads((root / "demo-build.json").read_text())
config = Path(demo["config"])
database = Path(demo["database"])
assert config.is_file() and database.is_file()
payload = yaml.safe_load(config.read_text())
assert payload["dashboard"]["demo_mode"] is True

app = Dashboard(config, database)
checks = {}
for code in ("USD", "INR", "GBP", "EUR", "AED"):
    data = app.analytics("Aug-2026", 3, "", "", "", "previous", code)
    assert data["meta"]["currency"] == code
    assert data["meta"]["demo_mode"] is True
    assert data["meta"]["baseline_complete"] is True
    assert data["driver_rows"] and data["transactions"]
    checks[code] = data["kpis"]["period"]["value"]

with sqlite3.connect(database) as connection:
    count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
assert count > 300

(root / "functional.json").write_text(json.dumps({
    "status": "green",
    "currencies": checks,
    "synthetic_transaction_count": count,
}, indent=2) + "\n")
(root / "receipt.json").write_text(json.dumps({
    "schema": "expense_bookkeeper_validation_v2",
    "status": "green",
    "sha": os.environ.get("GITHUB_SHA", "local-targeted-check"),
    "python": platform.python_version(),
}, indent=2) + "\n")
PY
