"""
write_sheet.py — append rows to the user's Google Sheet via gspread.

Credentials: loaded from `config.sheet.service_account_path` or env
`EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT`. Never bundled.

Sheet ID and tab names: from user config. Never hardcoded.

Modes:
  --dry-run   — print the row that would be appended, do not write
  --live      — append for real (default after setup completion)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

import gspread
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Canonical EXPENSES header order
HEADERS = [
    "Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
    "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
    "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason",
    "Hash",
]


def _load_config(path: str | Path) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def _client(service_account_path: str | Path):
    creds = Credentials.from_service_account_file(str(service_account_path), scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(config: dict):
    """Open the user-owned ledger from config without exposing credentials."""
    sa_path = config.get("sheet", {}).get("service_account_path") \
        or os.environ.get("EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT")
    if not sa_path:
        raise RuntimeError(
            "No service account path. Set sheet.service_account_path in config "
            "or EXPENSE_BOOKKEEPER_SERVICE_ACCOUNT env."
        )
    sheet_id = (config.get("sheet", {}).get("id") or "").strip()
    if not sheet_id:
        raise RuntimeError("No Google Sheet ID. Set sheet.id in config.")
    return _client(Path(sa_path).expanduser()).open_by_key(sheet_id)


def _existing_hashes(ws) -> set[str]:
    """Read the canonical Hash column; fail closed if the header is missing."""
    values = ws.get_all_values()
    for header_index, row in enumerate(values):
        normalized = [(cell or "").strip() for cell in row]
        if "Hash" not in normalized:
            continue
        hash_index = normalized.index("Hash")
        return {
            str(data_row[hash_index]).strip()
            for data_row in values[header_index + 1:]
            if len(data_row) > hash_index and str(data_row[hash_index]).strip()
        }
    raise RuntimeError("EXPENSES is missing the required Hash header; append refused")


def append_rows(config: dict, rows: Sequence[Sequence[str]], dry_run: bool = False) -> int:
    tab = config.get("sheet", {}).get("expenses_tab", "EXPENSES")

    if dry_run:
        print("[DRY-RUN] would append:")
        for r in rows:
            print(" ", dict(zip(HEADERS, r)))
        return 0

    sh = open_spreadsheet(config)
    ws = sh.worksheet(tab)
    seen_hashes = _existing_hashes(ws)
    hash_index = HEADERS.index("Hash")
    filtered_rows: list[Sequence[str]] = []
    for row in rows:
        row_hash = str(row[hash_index]).strip() if len(row) > hash_index else ""
        if row_hash and row_hash in seen_hashes:
            continue
        filtered_rows.append(row)
        if row_hash:
            seen_hashes.add(row_hash)
    if not filtered_rows:
        return 0
    ws.append_rows(filtered_rows, value_input_option="USER_ENTERED")
    return len(filtered_rows)


def transaction_to_row(txn: dict) -> list[str]:
    """Map a structured txn dict to the EXPENSES row in HEADERS order."""
    from datetime import datetime
    date = txn.get("date", "")
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        day = d.strftime("%a")
        month_year = d.strftime("%b-%Y")
    except Exception:
        day = ""; month_year = ""
    txn_id = txn.get("txn_id", "")
    if not txn_id:
        # A parsed transaction hash is stable across duplicate capture paths.
        # Fall back to a microsecond timestamp only for callers without a hash.
        stable_hash = str(txn.get("hash") or "").strip()
        txn_id = (
            "TXN" + stable_hash.upper()
            if stable_hash
            else "TXN" + datetime.now().strftime("%Y%m%d%H%M%S%f")
        )
    return [
        txn_id,
        date,
        day,
        month_year,
        f"{float(txn.get('amount') or 0):.2f}",
        txn.get("currency", ""),
        txn.get("txn_type", "Expense"),
        txn.get("category", ""),
        txn.get("subcategory", ""),
        txn.get("merchant_raw", ""),
        txn.get("merchant_clean", ""),
        txn.get("card", ""),
        txn.get("source", ""),
        txn.get("person", "Household"),
        txn.get("notes", ""),
        txn.get("status", "Confirmed"),
        txn.get("review_reason", ""),
        txn.get("hash", ""),
    ]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--txn-json", required=True, help="JSON dict with transaction fields")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = _load_config(args.config)
    txn = json.loads(args.txn_json)
    row = transaction_to_row(txn)
    n = append_rows(cfg, [row], dry_run=args.dry_run)
    print(f"appended {n} rows")
