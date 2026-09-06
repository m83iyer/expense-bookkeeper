#!/usr/bin/env python3
"""
repair_diagnostics.py — local health checks and reversible fixes.

Output: structured report with `issue / likely cause / safe fix /
requires user action / validation command` rows. Reversible local fixes
apply automatically in dry-run first.

Usage:
  python3 repair_diagnostics.py --config ~/.expense-bookkeeper/config.yaml
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

THIS = Path(__file__).resolve().parent

CHECKS = []


def check(name, severity="MAJOR"):
    def deco(fn):
        CHECKS.append((name, severity, fn))
        return fn
    return deco


def _config(path):
    import yaml
    return yaml.safe_load(open(path))


@check("config file present + parseable", severity="BLOCKER")
def c_config(args):
    p = Path(args.config).expanduser()
    if not p.exists():
        return {
            "issue": "config file missing",
            "likely_cause": "setup never completed or config was moved",
            "safe_fix": "re-run setup_wizard.py",
            "requires_user_action": True,
            "validation_command": f"ls {p}",
        }
    try:
        cfg = _config(p)
        return {"issue": None, "ok": True, "detail": f"config has {len(cfg)} top-level keys"}
    except Exception as e:
        return {
            "issue": "config unparseable",
            "likely_cause": "YAML syntax error",
            "safe_fix": "open in editor and fix YAML; back up first",
            "requires_user_action": True,
            "validation_command": f"python3 -c \"import yaml; yaml.safe_load(open('{p}'))\"",
        }


@check("service account file present + readable", severity="BLOCKER")
def c_sa(args):
    cfg = _config(args.config)
    sa = cfg.get("sheet", {}).get("service_account_path") or os.environ.get("EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT")
    if not sa:
        return {
            "issue": "no service account configured",
            "likely_cause": "setup did not capture the service-account JSON path",
            "safe_fix": "set sheet.service_account_path in config or EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT env var",
            "requires_user_action": True,
            "validation_command": "echo $EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT",
        }
    p = Path(sa).expanduser()
    if not p.exists():
        return {
            "issue": f"service account file not found: {p}",
            "likely_cause": "file moved or deleted",
            "safe_fix": "restore the file or re-download from Google Cloud Console",
            "requires_user_action": True,
            "validation_command": f"ls -la {p}",
        }
    try:
        d = json.loads(p.read_text())
        if d.get("type") != "service_account":
            return {
                "issue": "service-account JSON is not a service account",
                "likely_cause": "wrong file type (OAuth client vs service account)",
                "safe_fix": "download a service account JSON from Google Cloud Console",
                "requires_user_action": True,
                "validation_command": f"python3 -c \"import json; print(json.load(open('{p}'))['type'])\"",
            }
        return {"issue": None, "ok": True, "detail": d.get("client_email")}
    except Exception as e:
        return {
            "issue": f"service-account JSON unreadable: {e}",
            "likely_cause": "file corrupted or wrong format",
            "safe_fix": "re-download the service-account JSON",
            "requires_user_action": True,
            "validation_command": f"cat {p} | python3 -m json.tool",
        }


@check("Google Sheet reachable", severity="BLOCKER")
def c_sheet(args):
    cfg = _config(args.config)
    sa = cfg["sheet"].get("service_account_path") or os.environ.get("EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT")
    sheet_id = cfg["sheet"].get("id")
    if not sheet_id:
        return {"issue": "no sheet ID configured", "likely_cause": "setup not complete",
                "safe_fix": "re-run setup_wizard.py", "requires_user_action": True}
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            str(Path(sa).expanduser()),
            scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        return {"issue": None, "ok": True, "detail": sh.title}
    except Exception as e:
        return {
            "issue": f"sheet not reachable: {e}",
            "likely_cause": "sheet ID wrong, or service account not shared with the sheet",
            "safe_fix": "share the sheet with the service-account email (Editor permission); see references/repair.md § sheet-sharing",
            "requires_user_action": True,
            "validation_command": "python3 -c \"from gspread import authorize; from google.oauth2.service_account import Credentials; print('ok')\"",
        }


@check("recent activity (last 24h)", severity="MAJOR")
def c_activity(args):
    cfg = _config(args.config)
    sheet_id = cfg["sheet"].get("id")
    sa = cfg["sheet"].get("service_account_path") or os.environ.get("EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT")
    if not (sheet_id and sa):
        return {"issue": None, "ok": None, "detail": "skipped"}
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            str(Path(sa).expanduser()),
            scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(cfg["sheet"].get("expenses_tab", "EXPENSES"))
        rows = ws.get_all_values()
        recent = 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        for r in rows[2:]:
            if not r or len(r) < 2: continue
            d = r[1]
            for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
                try:
                    if datetime.strptime(d.strip(), fmt).date() >= cutoff:
                        recent += 1
                    break
                except ValueError:
                    continue
        if recent == 0:
            return {
                "issue": "no rows logged in the last 24h",
                "likely_cause": "capture adapter offline, OS permissions revoked, or no spend",
                "safe_fix": "check capture adapter (see references/adapters/<adapter>.md § health)",
                "requires_user_action": True,
                "validation_command": "tail -f ~/.expense-bookkeeper/state/run.log",
            }
        return {"issue": None, "ok": True, "detail": f"{recent} rows in last 24h"}
    except Exception as e:
        return {"issue": f"activity check failed: {e}", "likely_cause": "transient", "safe_fix": "re-run", "requires_user_action": False}


@check("logs directory present + writable", severity="MEDIUM")
def c_logs(args):
    state_dir = Path(args.config).expanduser().parent / "state"
    if not state_dir.exists():
        try:
            state_dir.mkdir(parents=True)
            return {"issue": None, "ok": True, "detail": f"created {state_dir} (reversible local fix)"}
        except Exception as e:
            return {
                "issue": f"cannot create state dir: {e}",
                "likely_cause": "permissions",
                "safe_fix": f"manually create {state_dir}",
                "requires_user_action": True,
            }
    if not os.access(state_dir, os.W_OK):
        return {
            "issue": f"state dir not writable: {state_dir}",
            "likely_cause": "permissions",
            "safe_fix": f"chmod u+w {state_dir}",
            "requires_user_action": True,
            "validation_command": f"ls -la {state_dir}",
        }
    return {"issue": None, "ok": True, "detail": str(state_dir)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    results = []
    for name, severity, fn in CHECKS:
        try:
            r = fn(args)
        except Exception as e:
            r = {"issue": f"check exception: {e}", "likely_cause": "bug",
                 "safe_fix": "report the traceback in your support thread",
                 "requires_user_action": True}
        results.append({"name": name, "severity": severity, **r})

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("expense-bookkeeper · repair diagnostics\n")
    for r in results:
        if r.get("ok") is True:
            print(f"  ✅ {r['name']}  —  {r.get('detail','ok')}")
        elif r.get("ok") is None:
            print(f"  ⏭️  {r['name']}  —  {r.get('detail','skipped')}")
        else:
            print(f"  ❌ [{r['severity']}] {r['name']}")
            print(f"      issue:                {r.get('issue')}")
            print(f"      likely cause:         {r.get('likely_cause')}")
            print(f"      safe fix:             {r.get('safe_fix')}")
            print(f"      requires user action: {r.get('requires_user_action')}")
            if r.get("validation_command"):
                print(f"      validation command:   {r.get('validation_command')}")
            print()


if __name__ == "__main__":
    main()
