#!/usr/bin/env python3
"""Serve the private expense-bookkeeper dashboard and analytics API."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.capture_pipeline import process_raw_event
from scripts.write_sheet import _load_config
from dashboard.fx import currency_context
from dashboard.intelligence import build_analytics, month_key, shift_month

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": (STATIC / "index.html", "text/html; charset=utf-8"),
    "/index.html": (STATIC / "index.html", "text/html; charset=utf-8"),
    "/styles.css": (STATIC / "styles.css", "text/css; charset=utf-8"),
    "/app.js": (STATIC / "app.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": (STATIC / "manifest.webmanifest", "application/manifest+json"),
}
DEFAULT_CONFIG = Path("~/.expense-bookkeeper/config.yaml").expanduser()
DEFAULT_DB = Path("~/.expense-bookkeeper/state/dashboard.sqlite3").expanduser()


class Dashboard:
    def __init__(self, config_path: Path, database_path: Path | None = None):
        self.config_path = config_path.expanduser()
        self.config = _load_config(self.config_path)
        configured = self.config.get("dashboard", {}).get("database_path")
        self.database = (database_path or Path(os.environ.get("EXPENSE_BOOKKEEPER_DASHBOARD_DB") or configured or DEFAULT_DB)).expanduser()
        self.cash_enabled = bool(self.config.get("dashboard", {}).get("allow_cash_entry", False))
        self.allow_lan_writes = bool(self.config.get("dashboard", {}).get("allow_lan_writes", False))
        self.demo_mode = bool(self.config.get("dashboard", {}).get("demo_mode", False))
        self.write_token = os.environ.get("EXPENSE_BOOKKEEPER_DASHBOARD_WRITE_TOKEN", "")

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in conn.execute(sql, params)]
        finally:
            conn.close()

    def metadata(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.rows("SELECT key,value FROM metadata")}

    def analytics(
        self,
        selected_month: str,
        range_months: int,
        category: str,
        subcategory: str,
        merchant: str = "",
        comparison: str = "previous",
        display_currency: str = "",
    ) -> dict:
        ledger = self.rows(
            "SELECT * FROM transactions WHERE lower(status)='confirmed' AND lower(txn_type)='expense'"
        )
        metadata = self.metadata()
        base = metadata.get("currency", self.config.get("locale", {}).get("default_currency", "USD")).upper()
        fx = currency_context(self.config, base, display_currency)
        return build_analytics(
            ledger,
            metadata,
            selected_month=selected_month,
            range_months=range_months,
            category=category,
            subcategory=subcategory,
            merchant=merchant,
            comparison=comparison,
            fx=fx,
            cash_entry_enabled=self.cash_enabled,
            demo_mode=self.demo_mode,
        )

    def commitments(self, display_currency: str = "") -> dict:
        items = self.rows("SELECT * FROM recurring ORDER BY monthly_amount DESC")
        metadata = self.metadata()
        base = metadata.get("currency", self.config.get("locale", {}).get("default_currency", "USD")).upper()
        fx = currency_context(self.config, base, display_currency)
        factor = float(fx["rate"])
        monthly = sum(float(item["monthly_amount"]) for item in items)
        today = date.today()
        upcoming = []
        converted_items = []
        for item in items:
            cadence = item.get("cadence") or "monthly"
            payment_amount = float(item.get("payment_amount") or item["monthly_amount"])
            converted = {
                **item,
                "cadence": cadence,
                "payment_amount": round(payment_amount * factor, 2),
                "monthly_amount": round(float(item["monthly_amount"]) * factor, 2),
                "annual_amount": round(float(item["monthly_amount"]) * 12 * factor, 2),
            }
            converted_items.append(converted)
            # A day-of-month identifies the next monthly payment. It does not
            # identify the month of an annual or quarterly payment, so those
            # cadences remain in the register but are excluded from the dated
            # timeline unless a future schema supplies an exact due date.
            if cadence == "monthly":
                day = min(item.get("day_of_month") or 1, 28)
                due = date(today.year, today.month, day)
                if due < today:
                    next_month = shift_month(today.strftime("%b-%Y"), 1)
                    year, month = month_key(next_month)
                    due = date(year, month, day)
                upcoming.append({**converted, "amount": converted["payment_amount"], "due_date": due.isoformat()})
        return {
            "commitments": converted_items,
            "upcoming": sorted(upcoming, key=lambda i: i["due_date"]),
            "monthly_equivalent": round(monthly * factor, 2),
            "annual_total": round(monthly * 12 * factor, 2),
            "currency": fx["quote"],
            "fx_as_of": fx.get("as_of"),
            "demo_mode": self.demo_mode,
        }

    def log_cash(self, payload: dict) -> dict:
        amount = float(payload.get("amount") or 0)
        merchant = str(payload.get("merchant") or "").strip()
        if amount <= 0 or not merchant:
            raise ValueError("A positive amount and merchant are required.")
        currency = self.config.get("locale", {}).get("default_currency", "USD")
        day = str(payload.get("date") or date.today().isoformat())
        try:
            parsed_day = date.fromisoformat(day)
        except ValueError as exc:
            raise ValueError("Cash-entry date must use YYYY-MM-DD.") from exc
        raw = f"{currency} {amount:.2f} at {merchant} on {parsed_day.strftime('%d-%m-%Y')}"
        result = process_raw_event(
            raw,
            self.config,
            source="dashboard_cash",
            category_override=str(payload.get("category") or "").strip(),
            subcategory_override=str(payload.get("subcategory") or "").strip(),
            notes=str(payload.get("notes") or "").strip(),
        )
        return {"status": "logged" if result["appended"] else "duplicate", "amount": amount, "merchant": merchant,
                "review": result["transaction"].get("status") == "Review"}


class Handler(BaseHTTPRequestHandler):
    server_version = "ExpenseBookkeeperDashboard/2.0"

    def _headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                         "frame-ancestors 'none'; form-action 'self'")

    def json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed, app = urlparse(self.path), self.server.dashboard
        try:
            if parsed.path == "/api/analytics":
                query = parse_qs(parsed.query)
                try:
                    months = int(query.get("range", ["12"])[0])
                except ValueError:
                    months = 12
                return self.json(app.analytics(query.get("month", [""])[0], months,
                                               query.get("category", [""])[0],
                                               query.get("subcategory", [""])[0],
                                               query.get("merchant", [""])[0],
                                               query.get("comparison", ["previous"])[0],
                                               query.get("currency", [""])[0]))
            if parsed.path == "/api/commitments":
                query = parse_qs(parsed.query)
                return self.json(app.commitments(query.get("currency", [""])[0]))
            if parsed.path == "/api/health":
                metadata = app.metadata()
                return self.json({
                    "status": "ok",
                    "synced_at": metadata.get("synced_at", "Not synced"),
                    "transaction_count": int(metadata.get("transaction_count", "0")),
                    "dashboard_schema": metadata.get("dashboard_schema", "1"),
                })
            static_file = STATIC_FILES.get(parsed.path)
            if static_file is None:
                raise FileNotFoundError
            path, content_type = static_file
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception:
            self.json(
                {"status": "error", "message": "Dashboard data is unavailable; run dashboard-sync and check local logs."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def do_POST(self) -> None:
        app = self.server.dashboard
        if urlparse(self.path).path != "/api/cash":
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not app.cash_enabled:
            return self.json({"status": "error", "message": "Cash entry is disabled."}, HTTPStatus.FORBIDDEN)
        remote = self.client_address[0]
        if not app.allow_lan_writes and remote not in {"127.0.0.1", "::1"}:
            return self.json({"status": "error", "message": "LAN writes are disabled."}, HTTPStatus.FORBIDDEN)
        if not app.write_token or self.headers.get("X-Expense-Write-Token", "") != app.write_token:
            return self.json({"status": "error", "message": "A valid local write token is required."}, HTTPStatus.UNAUTHORIZED)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("Invalid request size.")
            return self.json(app.log_cash(json.loads(self.rfile.read(length))), HTTPStatus.CREATED)
        except (ValueError, json.JSONDecodeError) as exc:
            return self.json({"status": "error", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            return self.json({"status": "error", "message": "Cash entry failed; check local logs."},
                             HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args) -> None:
        return


def serve(config: Path, database: Path | None, host: str, port: int) -> None:
    app = Dashboard(config, database)
    server = ThreadingHTTPServer((host, port), Handler)
    server.dashboard = app
    print(f"Expense Bookkeeper dashboard listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 only for a trusted private LAN")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.config, args.database, args.host, args.port)


if __name__ == "__main__":
    main()
