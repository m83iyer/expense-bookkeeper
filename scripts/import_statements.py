#!/usr/bin/env python3
"""
import_statements.py — bootstrap a new install from the user's past statements.

v1 limitations (honest):
  - **CSV only.** Excel and PDF are recipe-only — convert to CSV first.
  - No bank-format pattern auto-extraction (claim removed; v1.1 item).
  - No category auto-inference (the wizard exports merchant frequencies
    only; the user fills in Category/Subcategory in the proposed master).

Reads CSVs from `config.statements.path`, extracts unique merchants with
frequency + amount totals, writes:

  ~/.expense-bookkeeper/state/merchant_master_proposed.csv

(Note: the file name is `merchant_master_proposed.csv`; setup wizard's
`--resume-from-master` consumes this file.)
"""
from __future__ import annotations
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))


def _read_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if any((c or "").strip() for c in r)]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(args.config))
    folder = Path(cfg["statements"]["path"]).expanduser()
    if not folder.exists():
        print(f"folder not found: {folder}", file=sys.stderr); sys.exit(1)

    state_dir = Path(args.config).parent / "state"
    state_dir.mkdir(exist_ok=True)

    merchant_freq = Counter()
    merchant_amounts = defaultdict(list)

    for f in folder.glob("*.csv"):
        rows = _read_csv(f)
        if not rows: continue
        # Find merchant + amount columns by header
        header = rows[0]
        low = [c.lower() for c in header]
        i_m = next((i for i, c in enumerate(low) if "merchant" in c or "description" in c or "narrative" in c), None)
        i_a = next((i for i, c in enumerate(low) if "amount" in c or "debit" in c or "value" in c), None)
        if i_m is None: continue
        for r in rows[1:]:
            if len(r) <= i_m: continue
            m = (r[i_m] or "").strip()
            if not m: continue
            merchant_freq[m] += 1
            if i_a is not None and i_a < len(r):
                try:
                    a = float((r[i_a] or "").replace(",", ""))
                    merchant_amounts[m].append(a)
                except ValueError:
                    pass

    # Write proposed merchant master
    out_master = state_dir / "merchant_master_proposed.csv"
    with open(out_master, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Frequency", "Total_Amount"])
        for m, freq in merchant_freq.most_common():
            total = sum(merchant_amounts[m])
            w.writerow([m, m, "", "", freq, f"{total:.2f}"])

    print(f"Found {len(merchant_freq)} unique merchants from {sum(1 for _ in folder.glob('*.csv'))} CSV files")
    print(f"Proposed master: {out_master}")
    print("Next: open the file, fill in Category/Subcategory for each merchant,")
    print(f"then run: python3 scripts/setup_wizard.py --resume-from-master {out_master}")


if __name__ == "__main__":
    main()
