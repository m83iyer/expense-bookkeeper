#!/usr/bin/env python3
"""recurring_writer.py — daily check on the RECURRING tab; post any due entries to EXPENSES.

Reads the user's Google Sheet RECURRING tab, finds rows where:
  - Active == TRUE
  - Cadence == "monthly" (v1; weekly/yearly are v1.1)
  - today.day == Day_of_Month
  - Last_Posted month-year != current month-year
…and writes one EXPENSES row per due entry. Uses sha1 hash for dedup so
re-runs same day produce zero new rows.

Run via launchd daily at 03:00 user-local. See templates/launchd/
recurring_writer.plist for the agent template.

Idempotent: each due row produces a deterministic Txn_ID and hash; running
twice on the same day is a no-op.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime
from pathlib import Path

import gspread
import yaml
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _txn_hash(d: str, amount: float, description: str) -> str:
    base = f"{d}|{amount:.2f}|{description.strip().lower()}"
    # Keep the established ledger key stable. This hash is used for duplicate
    # detection only, not for authentication or integrity protection.
    return hashlib.sha1(base.encode(), usedforsecurity=False).hexdigest()[:16]


def _parse_amount(s) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return None


def _is_truthy(s) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes", "y")


def _today_month_year() -> str:
    return date.today().strftime("%b-%Y")


def post_due_entries(sh, today: date | None = None, dry_run: bool = False) -> dict:
    """Walk the RECURRING tab, post any due rows to EXPENSES.

    Returns: {"checked": N, "due": M, "posted": K, "skipped_already_posted": S}.
    """
    today = today or date.today()
    today_month_year = today.strftime("%b-%Y")

    try:
        recurring = sh.worksheet("RECURRING")
    except gspread.WorksheetNotFound:
        return {"error": "RECURRING tab missing — run create_ledger.py to provision"}
    try:
        expenses = sh.worksheet("EXPENSES")
    except gspread.WorksheetNotFound:
        return {"error": "EXPENSES tab missing"}

    rows = recurring.get_all_values()
    if len(rows) < 3:
        return {"checked": 0, "due": 0, "posted": 0, "skipped_already_posted": 0}

    # Header is row 2 (banner is row 1, per create_ledger.py convention)
    headers = rows[1]
    data_rows = rows[2:]

    def col(name: str, row: list[str]) -> str:
        try:
            return row[headers.index(name)]
        except (ValueError, IndexError):
            return ""

    posted = []
    skipped_already_posted = 0
    due = 0

    for i, row in enumerate(data_rows, start=3):  # 3 because banner=1, headers=2
        if not _is_truthy(col("Active", row)):
            continue
        cadence = col("Cadence", row).strip().lower()
        if cadence != "monthly":
            # v1 supports monthly only; weekly/yearly will land in v1.1
            continue
        try:
            day_of_month = int(col("Day_of_Month", row).strip())
        except (ValueError, TypeError):
            continue
        if day_of_month != today.day:
            continue

        due += 1

        last_posted = col("Last_Posted", row).strip()
        # Skip if already posted this calendar month
        if last_posted:
            try:
                lp_dt = datetime.strptime(last_posted, "%Y-%m-%d").date()
                if lp_dt.strftime("%b-%Y") == today_month_year:
                    skipped_already_posted += 1
                    continue
            except ValueError:
                pass  # malformed Last_Posted → treat as not posted

        amount = _parse_amount(col("Amount", row))
        description = col("Description", row).strip()
        if not amount or amount <= 0 or not description:
            continue

        txn_date = today.strftime("%Y-%m-%d")
        txn_id = f"REC{today.strftime('%Y%m%d')}{i:03d}"
        h = _txn_hash(txn_date, amount, description)

        new_row = [
            txn_id,                                  # Txn_ID
            txn_date,                                # Date
            today.strftime("%a"),                    # Day
            today_month_year,                        # Month-Year
            f"{amount:.2f}",                         # Amount
            col("Currency", row) or "AED",           # Currency
            "Expense",                               # Txn_Type
            col("Category", row),                    # Category
            col("Subcategory", row),                 # Subcategory
            description,                             # Merchant_Raw
            description,                             # Merchant_Clean
            col("Card_Used", row) or "Recurring",    # Card_Used
            "Recurring",                             # Source
            col("Person", row) or "Household",       # Person
            col("Notes", row),                       # Notes
            "Confirmed",                             # Status
            "",                                      # Review_Reason
            h,                                       # Hash
        ]

        if not dry_run:
            expenses.append_row(new_row, value_input_option="USER_ENTERED")
            recurring.update_cell(i, headers.index("Last_Posted") + 1, txn_date)

        posted.append({"row": i, "txn_id": txn_id, "amount": amount, "description": description})

    return {
        "checked": len(data_rows),
        "due": due,
        "posted": len(posted),
        "skipped_already_posted": skipped_already_posted,
        "details": posted,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="Override today as YYYY-MM-DD (testing)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(Path(args.config).expanduser()))
    sa = cfg["sheet"]["service_account_path"]
    sheet_id = cfg["sheet"]["id"]

    creds = Credentials.from_service_account_file(str(Path(sa).expanduser()), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    today = date.fromisoformat(args.date) if args.date else None
    result = post_due_entries(sh, today=today, dry_run=args.dry_run)

    print(f"recurring_writer: checked={result.get('checked', 0)} "
          f"due={result.get('due', 0)} "
          f"posted={result.get('posted', 0)} "
          f"skipped_already_posted={result.get('skipped_already_posted', 0)}"
          + (f" [DRY RUN]" if args.dry_run else ""))
    if result.get("error"):
        print(f"  error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    for d in result.get("details", []):
        print(f"  posted: {d['txn_id']}  {d['amount']:.2f}  {d['description']}")


if __name__ == "__main__":
    main()
