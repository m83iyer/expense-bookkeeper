#!/usr/bin/env python3
"""
create_ledger.py — provision a fresh Google Sheet from the canonical template.

Creates a new Google Sheet with the standard tabs and headers, then writes
the new sheet ID back into the user's config.

Usage:
  python3 create_ledger.py --config ~/.expense-bookkeeper/config.yaml \
      --title "My Expense Tracker"
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TABS = {
    "EXPENSES": [
        "HOUSEHOLD EXPENSE TRACKER  |  EXPENSES LOG",
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason",
         "Hash"],
    ],
    "MERCHANT_MASTER": [
        "MERCHANT MASTER  |  Keyword → Taxonomy mapping",
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory",
         "Aliases", "Last_Updated"],
    ],
    "CATEGORIES": [
        "CATEGORIES  |  Top-level taxonomy",
        ["Category", "Subcategory", "Active", "Notes"],
    ],
    "REVIEW_QUEUE": [
        "REVIEW QUEUE  |  Optional workspace for adapter-specific review flows",
        ["Review_ID", "Date", "Amount", "Currency", "Merchant_Raw",
         "Suggested_Category", "Suggested_Subcategory", "Reason", "Status"],
    ],
    "RECONCILIATION": [
        "RECONCILIATION  |  Statement-vs-ledger diffs awaiting resolution",
        ["Run_ID", "Date", "Amount", "Currency", "Merchant_Raw",
         "Status", "Resolution"],
    ],
    "RECURRING": [
        "RECURRING  |  Fixed monthly entries written to EXPENSES automatically (rent, househelp, cash, etc.)",
        ["Description", "Amount", "Currency", "Category", "Subcategory",
         "Cadence", "Day_of_Month", "Active", "Card_Used", "Person", "Last_Posted", "Notes"],
    ],
    "EXPENSES_TEST": [
        "EXPENSES TEST  |  Dry-run target",
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason",
         "Hash"],
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--title", default="My Expense Tracker")
    args = ap.parse_args()

    import yaml
    cfg_path = Path(args.config).expanduser()
    cfg = yaml.safe_load(open(cfg_path))
    sa = cfg["sheet"]["service_account_path"]

    creds = Credentials.from_service_account_file(str(Path(sa).expanduser()), scopes=SCOPES)
    gc = gspread.authorize(creds)

    sh = gc.create(args.title)
    print(f"created: {sh.title}  ({sh.id})")

    # Default first sheet → rename to first tab in our list
    first_tab_name = list(TABS)[0]
    default_ws = sh.sheet1
    default_ws.update_title(first_tab_name)
    banner, headers = TABS[first_tab_name]
    default_ws.update(values=[[banner]], range_name="A1")
    default_ws.update(values=[headers], range_name="A2")

    # Add the rest
    for tab_name, (banner, headers) in list(TABS.items())[1:]:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=max(len(headers), 18))
        ws.update(values=[[banner]], range_name="A1")
        ws.update(values=[headers], range_name="A2")

    # Share with the user (instruction only — service account already owns it)
    user_email = ask_or_default("Your Google email (will get Editor access)", "")
    if user_email:
        sh.share(user_email, perm_type="user", role="writer", notify=True)

    cfg["sheet"]["id"] = sh.id
    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"wrote sheet ID back into {cfg_path}")
    print(f"sheet URL: https://docs.google.com/spreadsheets/d/{sh.id}/edit")


def ask_or_default(prompt, default):
    try:
        v = input(f"{prompt} [{default}]: ").strip()
        return v or default
    except EOFError:
        return default


if __name__ == "__main__":
    main()
