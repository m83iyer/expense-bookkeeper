#!/usr/bin/env python3
"""
reconcile_statement.py — diff a bank statement against the user's ledger.

Surfaces gaps (statement rows with no ledger counterpart) without auto-merging.
The user resolves each gap explicitly.

Usage:
  python3 reconcile_statement.py --config ~/.expense-bookkeeper/config.yaml \
      --statement path/to/statement.csv

Match rule:
  Same date (±2 days), same amount (±1%), similar descriptor (token overlap > 0.5)
  → MATCHED. Otherwise → GAP.
"""
from __future__ import annotations
import argparse
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))


def _norm_amount(s):
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return None


def _parse_date(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try: return datetime.strptime(s, f).date()
        except ValueError: continue
    return None


def _token_overlap(a, b):
    a = set((a or "").lower().split())
    b = set((b or "").lower().split())
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def load_statement_csv(path):
    """
    Tolerant CSV loader: looks for date / amount / merchant columns by name.
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = None
        for r in reader:
            low = [c.strip().lower() for c in r]
            if not header and any("date" in c for c in low) and any("amount" in c or "value" in c for c in low):
                header = r
                continue
            if header is None:
                continue
            d = dict(zip([h.strip() for h in header], r))
            rows.append(d)
    out = []
    for d in rows:
        # find columns by case-insensitive substring
        keys = {k.lower(): k for k in d}
        date_k = next((keys[k] for k in keys if "date" in k), None)
        amt_k = next((keys[k] for k in keys if "amount" in k or "value" in k or "debit" in k), None)
        m_k = next((keys[k] for k in keys if "merchant" in k or "description" in k or "narrative" in k), None)
        if not (date_k and amt_k and m_k):
            continue
        out.append({
            "date": _parse_date(d.get(date_k, "")),
            "amount": _norm_amount(d.get(amt_k, "")),
            "merchant_raw": (d.get(m_k) or "").strip(),
        })
    return [r for r in out if r["date"] and r["amount"]]


def reconcile(statement_rows, ledger_rows, date_window_days=2, amount_tol=0.01, descriptor_threshold=0.5):
    """
    statement_rows : list of {date, amount, merchant_raw}
    ledger_rows    : list of {Date, Amount, Merchant_Raw, Merchant_Clean}
    Returns:        list of {statement_row, status, ledger_match (or None), reason}
    """
    out = []
    for s in statement_rows:
        match = None
        for l in ledger_rows:
            d = _parse_date(l.get("Date", ""))
            a = _norm_amount(l.get("Amount") or l.get("Amount (AED)"))
            if not (d and a):
                continue
            if abs((d - s["date"]).days) > date_window_days:
                continue
            if abs(a - s["amount"]) / max(s["amount"], 1) > amount_tol:
                continue
            ov = _token_overlap(s["merchant_raw"],
                                l.get("Merchant_Raw", "") + " " + l.get("Merchant_Clean", ""))
            if ov >= descriptor_threshold:
                match = l
                break
        out.append({
            "statement": s,
            "status": "MATCHED" if match else "GAP",
            "ledger_match": match,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--statement", required=True)
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(args.config))

    # Load ledger from sheet
    import gspread
    from google.oauth2.service_account import Credentials
    sa = cfg["sheet"]["service_account_path"]
    creds = Credentials.from_service_account_file(
        str(Path(sa).expanduser()),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(cfg["sheet"]["id"])
    ws = sh.worksheet(cfg["sheet"].get("expenses_tab", "EXPENSES"))
    raw = ws.get_all_values()
    headers = raw[1] if len(raw) >= 2 else raw[0]
    ledger = [dict(zip(headers, r)) for r in raw[2:]]

    statement = load_statement_csv(args.statement)
    print(f"Loaded {len(statement)} statement rows, {len(ledger)} ledger rows")

    results = reconcile(statement, ledger)
    matched = sum(1 for r in results if r["status"] == "MATCHED")
    gaps = [r for r in results if r["status"] == "GAP"]
    print(f"\nMatched: {matched}  Gaps: {len(gaps)}")
    if gaps:
        print("\nGaps to resolve:")
        for r in gaps:
            s = r["statement"]
            print(f"  {s['date']}  AED {s['amount']:.2f}  {s['merchant_raw']}")


if __name__ == "__main__":
    main()
