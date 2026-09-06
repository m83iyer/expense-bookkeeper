#!/usr/bin/env python3
"""expense-bookkeeper — standalone CLI entry point.

Lets standalone users run the same workflow that skill users get:
    setup        — interactive wizard: builds config, provisions Google Sheet,
                   imports past statements, builds merchant→category map,
                   wires capture + confirm adapters, seeds recurring, validates
    run-recurring  — one-off run of the recurring writer (the daily 03:00 job)
    reconcile    — diff a statement CSV against the ledger
    validate     — run strict readiness gates including G8b safe write proof
    dashboard-sync  — refresh the local SQLite analytical mirror
    dashboard-fx-refresh — refresh the local five-currency reference-rate cache
    dashboard-demo  — build a deterministic privacy-safe Moneta demo
    dashboard-serve — serve the responsive private dashboard

All commands take `--config` (default: ~/.expense-bookkeeper/config.yaml).
The skill flow runs the same scripts via SKILL.md modes; this CLI is
the equivalent for users who do not use an agent runtime.

Usage:
    python3 cli.py setup
    python3 cli.py run-recurring
    python3 cli.py reconcile path/to/statement.csv
    python3 cli.py validate
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
SCRIPTS = THIS / "scripts"
DEFAULT_CONFIG = Path(os.path.expanduser("~/.expense-bookkeeper/config.yaml"))


def _run(script: str, args: list[str]) -> int:
    cmd = [sys.executable, str(SCRIPTS / script)] + args
    return subprocess.call(cmd)


def _run_module(module: str, args: list[str]) -> int:
    return subprocess.call([sys.executable, "-m", module, *args], cwd=THIS)


def cmd_setup(ns) -> int:
    return _run("setup_wizard.py", ["--out", str(ns.out)])


def cmd_run_recurring(ns) -> int:
    args = ["--config", str(ns.config)]
    if ns.dry_run:
        args.append("--dry-run")
    if ns.date:
        args += ["--date", ns.date]
    return _run("recurring_writer.py", args)


def cmd_reconcile(ns) -> int:
    return _run("reconcile_statement.py", ["--config", str(ns.config), "--statement", ns.statement])


def cmd_validate(ns) -> int:
    args = ["--config", str(ns.config)]
    if ns.dry_run:
        args.append("--dry-run")
    return _run("validate_install.py", args)


def cmd_learn_category(ns) -> int:
    args = ["--state", str(ns.state), "learn", ns.merchant, ns.category]
    if ns.subcategory:
        args += ["--subcategory", ns.subcategory]
    if ns.txn_id:
        args += ["--txn-id", ns.txn_id]
    return _run("adaptive_categories.py", args)


def cmd_category_status(ns) -> int:
    return _run("adaptive_categories.py", ["--state", str(ns.state), "status"])


def cmd_privacy_audit(ns) -> int:
    args = [ns.root]
    if ns.history:
        args += ["--history", "--history-ref", ns.history_ref]
    for term in ns.private_term:
        args += ["--private-term", term]
    return _run("privacy_audit.py", args)


def cmd_dashboard_sync(ns) -> int:
    args = ["--config", str(ns.config)]
    if ns.database:
        args += ["--database", str(ns.database)]
    return _run_module("dashboard.sync", args)


def cmd_dashboard_serve(ns) -> int:
    args = ["--config", str(ns.config), "--host", ns.host, "--port", str(ns.port)]
    if ns.database:
        args += ["--database", str(ns.database)]
    return _run_module("dashboard.server", args)


def cmd_dashboard_fx_refresh(ns) -> int:
    args = ["--config", str(ns.config)]
    if ns.output:
        args += ["--output", str(ns.output)]
    return _run_module("dashboard.fx", args)


def cmd_dashboard_demo(ns) -> int:
    return _run_module("dashboard.demo", ["--output", str(ns.output)])


def main():
    ap = argparse.ArgumentParser(
        prog="expense-bookkeeper",
        description="Personal expense tracker — standalone CLI. "
                    "Same workflow skill users get via the SKILL.md modes.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Run the one-time setup wizard")
    p_setup.add_argument("--out", default=os.path.expanduser("~/.expense-bookkeeper"),
                         help="Output folder for config + state (default: ~/.expense-bookkeeper)")
    p_setup.set_defaults(fn=cmd_setup)

    p_rec = sub.add_parser("run-recurring", help="Manually fire the recurring writer")
    p_rec.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_rec.add_argument("--dry-run", action="store_true")
    p_rec.add_argument("--date", help="Override today as YYYY-MM-DD (testing)")
    p_rec.set_defaults(fn=cmd_run_recurring)

    p_rec2 = sub.add_parser("reconcile", help="Diff a CSV statement against the ledger")
    p_rec2.add_argument("statement", help="Path to statement CSV")
    p_rec2.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_rec2.set_defaults(fn=cmd_reconcile)

    p_val = sub.add_parser("validate", help="Run strict readiness gates including G8b safe live-write proof")
    p_val.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_val.add_argument("--dry-run", action="store_true", default=True)
    p_val.set_defaults(fn=cmd_validate)

    default_adaptive_state = os.path.expanduser("~/.expense-bookkeeper/state/adaptive_categories.json")
    p_learn = sub.add_parser("learn-category", help="Learn a merchant mapping from a confirmed correction")
    p_learn.add_argument("merchant")
    p_learn.add_argument("category")
    p_learn.add_argument("--subcategory", default="")
    p_learn.add_argument("--txn-id", default="")
    p_learn.add_argument("--state", default=default_adaptive_state)
    p_learn.set_defaults(fn=cmd_learn_category)

    p_status = sub.add_parser("category-status", help="Show learned rules and pending proposals")
    p_status.add_argument("--state", default=default_adaptive_state)
    p_status.set_defaults(fn=cmd_category_status)

    p_privacy = sub.add_parser("privacy-audit", help="Scan a release tree for secrets and personal data")
    p_privacy.add_argument("root", nargs="?", default=".")
    p_privacy.add_argument("--history", action="store_true")
    p_privacy.add_argument("--history-ref", default="HEAD")
    p_privacy.add_argument("--private-term", action="append", default=[])
    p_privacy.set_defaults(fn=cmd_privacy_audit)

    p_sync = sub.add_parser("dashboard-sync", help="Refresh the dashboard's local SQLite mirror")
    p_sync.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_sync.add_argument("--database")
    p_sync.set_defaults(fn=cmd_dashboard_sync)

    p_dash = sub.add_parser("dashboard-serve", help="Serve the private responsive dashboard")
    p_dash.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_dash.add_argument("--database")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8765)
    p_dash.set_defaults(fn=cmd_dashboard_serve)

    p_fx = sub.add_parser("dashboard-fx-refresh", help="Refresh cached USD/INR/GBP/EUR/AED reference rates")
    p_fx.add_argument("--config", default=str(DEFAULT_CONFIG))
    p_fx.add_argument("--output")
    p_fx.set_defaults(fn=cmd_dashboard_fx_refresh)

    p_demo = sub.add_parser("dashboard-demo", help="Build a deterministic privacy-safe Moneta demo")
    p_demo.add_argument("--output", required=True)
    p_demo.set_defaults(fn=cmd_dashboard_demo)

    ns = ap.parse_args()
    sys.exit(ns.fn(ns))


if __name__ == "__main__":
    main()
