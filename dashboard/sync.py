#!/usr/bin/env python3
"""Build an atomic, read-optimized SQLite mirror of the Google Sheet ledger."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from gspread.exceptions import WorksheetNotFound

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.write_sheet import _load_config, open_spreadsheet

DEFAULT_DB = Path("~/.expense-bookkeeper/state/dashboard.sqlite3").expanduser()
EXPENSE_HEADERS = {
    "txn_id", "date", "amount", "currency", "txn_type", "category",
    "subcategory", "merchant_clean", "status",
}


def _clean_header(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _number(value: Any) -> float:
    text = str(value or "0").strip().replace(",", "")
    return float("".join(char for char in text if char.isdigit() or char in ".-") or 0)


def _date(value: Any, formats: Iterable[str]) -> str:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", *formats):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unsupported transaction date: {text!r}")


def normalize_expenses(values: list[list[Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    if not values:
        return []
    header_index = next(
        (index for index, row in enumerate(values) if EXPENSE_HEADERS <= {_clean_header(v) for v in row}),
        None,
    )
    if header_index is None:
        raise ValueError("EXPENSES header row was not found or is missing canonical fields.")
    headers = [_clean_header(value) for value in values[header_index]]
    formats = config.get("locale", {}).get("date_formats", []) or []
    output: list[dict[str, Any]] = []
    for row in values[header_index + 1:]:
        record = dict(zip(headers, list(row) + [""] * max(0, len(headers) - len(row))))
        if not str(record.get("txn_id", "")).strip():
            continue
        date = _date(record.get("date"), formats)
        amount = _number(record.get("amount"))
        output.append({
            "txn_id": str(record["txn_id"]).strip(),
            "date": date,
            "month_year": datetime.fromisoformat(date).strftime("%b-%Y"),
            "amount": abs(amount),
            "currency": str(record.get("currency") or config.get("locale", {}).get("default_currency") or "USD").upper(),
            "txn_type": str(record.get("txn_type") or "Expense").strip(),
            "category": str(record.get("category") or "Uncategorized").strip(),
            "subcategory": str(record.get("subcategory") or "Other").strip(),
            "merchant_clean": str(record.get("merchant_clean") or record.get("merchant_raw") or "Unknown Merchant").strip(),
            "card_used": str(record.get("card_used") or "").strip(),
            "source": str(record.get("source") or "").strip(),
            "person": str(record.get("person") or "").strip(),
            "notes": str(record.get("notes") or "").strip(),
            "status": str(record.get("status") or "Confirmed").strip(),
        })
    return output


def normalize_recurring(values: list[list[Any]], currency: str) -> list[dict[str, Any]]:
    if not values:
        return []
    headers = [_clean_header(value) for value in values[0]]
    factors = {
        "weekly": 52 / 12, "monthly": 1, "quarterly": 1 / 3,
        "half-yearly": 1 / 6, "semiannual": 1 / 6, "yearly": 1 / 12, "annual": 1 / 12,
    }
    result = []
    for row in values[1:]:
        item = dict(zip(headers, list(row) + [""] * max(0, len(headers) - len(row))))
        active = str(item.get("active", "")).strip().casefold() in {"true", "yes", "1", "active"}
        if not active or not str(item.get("description", "")).strip():
            continue
        amount = _number(item.get("amount"))
        cadence = str(item.get("cadence") or "monthly").strip().casefold()
        monthly = amount * factors.get(cadence, 1)
        result.append({
            "name": str(item["description"]).strip(),
            "category": str(item.get("category") or "Uncategorized").strip(),
            "subcategory": str(item.get("subcategory") or "Other").strip(),
            "currency": str(item.get("currency") or currency).upper(),
            "monthly_amount": round(monthly, 2),
            "day_of_month": int(_number(item.get("day_of_month"))) if item.get("day_of_month") else None,
            "cadence": cadence,
            "payment_amount": round(amount, 2),
        })
    return result


def build_database(
    target: Path,
    transactions: list[dict[str, Any]],
    recurring: list[dict[str, Any]],
    *,
    currency: str,
) -> None:
    normalized_recurring = [
        {
            **item,
            "cadence": str(item.get("cadence") or "monthly"),
            "payment_amount": float(item.get("payment_amount") or item.get("monthly_amount") or 0),
        }
        for item in recurring
    ]
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".dashboard-", suffix=".sqlite3", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        conn = sqlite3.connect(temporary)
        conn.executescript("""
            CREATE TABLE transactions (
              txn_id TEXT PRIMARY KEY, date TEXT NOT NULL, month_year TEXT NOT NULL,
              amount REAL NOT NULL, currency TEXT NOT NULL, txn_type TEXT NOT NULL,
              category TEXT NOT NULL, subcategory TEXT NOT NULL, merchant_clean TEXT NOT NULL,
              card_used TEXT, source TEXT, person TEXT, notes TEXT, status TEXT NOT NULL
            );
            CREATE INDEX idx_transactions_month ON transactions(month_year);
            CREATE INDEX idx_transactions_scope ON transactions(category, subcategory);
            CREATE TABLE recurring (
              name TEXT NOT NULL, category TEXT NOT NULL, subcategory TEXT NOT NULL,
              currency TEXT NOT NULL, monthly_amount REAL NOT NULL, day_of_month INTEGER,
              cadence TEXT NOT NULL DEFAULT 'monthly', payment_amount REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        conn.executemany(
            """INSERT INTO transactions VALUES
            (:txn_id,:date,:month_year,:amount,:currency,:txn_type,:category,:subcategory,
             :merchant_clean,:card_used,:source,:person,:notes,:status)""",
            transactions,
        )
        conn.executemany(
            """INSERT INTO recurring
            (name,category,subcategory,currency,monthly_amount,day_of_month,cadence,payment_amount)
            VALUES (:name,:category,:subcategory,:currency,:monthly_amount,:day_of_month,:cadence,:payment_amount)""",
            normalized_recurring,
        )
        conn.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("currency", currency), ("synced_at", datetime.now().astimezone().isoformat()),
            ("transaction_count", str(len(transactions))), ("dashboard_schema", "2"),
        ])
        conn.commit()
        conn.close()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def sync(config_path: Path, database_path: Path | None = None) -> dict[str, Any]:
    config = _load_config(config_path)
    book = open_spreadsheet(config)
    sheet = config.get("sheet", {})
    currency = config.get("locale", {}).get("default_currency", "USD")
    expenses = normalize_expenses(book.worksheet(sheet.get("expenses_tab", "EXPENSES")).get_all_values(), config)
    try:
        recurring_values = book.worksheet(sheet.get("recurring_tab", "RECURRING")).get_all_values()
    except WorksheetNotFound:
        recurring_values = []
    commitments = normalize_recurring(recurring_values, currency)
    mixed = sorted({
        item["currency"] for item in expenses
        if item["status"].casefold() == "confirmed"
        and item["txn_type"].casefold() == "expense"
        and item["currency"] != currency
    })
    if mixed:
        raise ValueError(
            "Dashboard totals require one normalized reporting currency. "
            f"Found {', '.join(mixed)} in addition to {currency}; convert those rows before syncing."
        )
    mixed_commitments = sorted({item["currency"] for item in commitments if item["currency"] != currency})
    if mixed_commitments:
        raise ValueError(
            "Recurring commitments must use the reporting currency "
            f"{currency}; found {', '.join(mixed_commitments)}."
        )
    configured = config.get("dashboard", {}).get("database_path")
    target = database_path or Path(os.environ.get("EXPENSE_BOOKKEEPER_DASHBOARD_DB") or configured or DEFAULT_DB)
    build_database(target, expenses, commitments, currency=currency)
    return {"status": "ok", "transactions": len(expenses), "commitments": len(commitments), "database": str(target)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("~/.expense-bookkeeper/config.yaml").expanduser())
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    print(sync(args.config, args.database))


if __name__ == "__main__":
    main()
