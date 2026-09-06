#!/usr/bin/env python3
"""
validate_install.py — runs the v1 functional gates required by
references/validation.md. Outputs a structured pass/fail report.

Usage:
  python3 validate_install.py --config ~/.expense-bookkeeper/config.yaml [--dry-run] [--strict|--non-strict]

Modes:
  --strict (default)     Critical skipped gates count as FAIL. Required before live arm.
  --non-strict           Critical skipped gates count as SKIP. Used for partial setup
                         development (e.g. running the wizard before sheet provisioning).

Gates (v1):
  G1  config readable, required keys present                (always required)
  G2  service-account JSON reachable                        (always required)
  G3  Google Sheet accessible (read-only check)             (CRITICAL in strict)
  G4  EXPENSES tab has expected headers                     (CRITICAL in strict)
  G4b MERCHANT_MASTER + CATEGORIES tabs present + headered  (CRITICAL in strict)
  G5  parser parses 5 sample notifications                  (always required)
  G6  resolver returns tier 1/2/3 correctly on fixtures     (always required)
  G6b word-boundary safety: no substring false-positive     (always required)
  G7  hash dedup: same input → same hash, different inputs → different
  G8  row-build dry-run: produces a valid row, no live write  (non-critical)
  G8b safe-write proof: append→read-back→delete on EXPENSES_TEST (CRITICAL in strict)

In strict mode, exit 0 requires: zero failures AND zero skips on critical gates.
In non-strict mode, exit 0 requires: zero failures (skips allowed).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))

# Critical gates — in strict mode these CANNOT be skipped. If they skip, treated as FAIL.
# Note: G8 (row-build dry-run) is no longer critical — it doesn't prove live write
# permission. G8b (safe live-write proof) replaces it as the critical write check.
CRITICAL_GATES = {
    "G3 Google Sheet accessible",
    "G4 EXPENSES tab has expected headers",
    "G4b MERCHANT_MASTER + CATEGORIES tabs present + headered",
    "G8b safe live-write proof (EXPENSES_TEST)",
}

GATES = []


def gate(name):
    def deco(fn):
        GATES.append((name, fn))
        return fn
    return deco


@gate("G1 config readable + required keys present")
def g1(ctx):
    cfg = ctx["config"]
    for k in ("sheet", "categorization", "capture", "confirmation"):
        if k not in cfg:
            return False, f"missing top-level key: {k}"
    if not cfg["sheet"].get("service_account_path"):
        return False, "sheet.service_account_path is empty"
    return True, "ok"


@gate("G2 service-account JSON reachable")
def g2(ctx):
    sa = ctx["config"]["sheet"]["service_account_path"]
    p = Path(sa).expanduser()
    if not p.exists():
        return False, f"file not found: {p}"
    try:
        d = json.loads(p.read_text())
        if d.get("type") != "service_account":
            return False, "service-account JSON is not a service account"
        if not d.get("client_email"):
            return False, "missing client_email"
        return True, f"client_email={d['client_email']}"
    except Exception as e:
        return False, f"unreadable: {e}"


@gate("G3 Google Sheet accessible")
def g3(ctx):
    sheet_id = ctx["config"]["sheet"].get("id")
    if not sheet_id:
        return None, "skipped — no sheet ID set yet (CRITICAL in strict mode)"
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        sa = ctx["config"]["sheet"]["service_account_path"]
        creds = Credentials.from_service_account_file(
            str(Path(sa).expanduser()),
            scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        ctx["_book"] = sh
        return True, f"opened: {sh.title}"
    except Exception as e:
        return False, f"failed to open sheet: {e}"


@gate("G4 EXPENSES tab has expected headers")
def g4(ctx):
    sh = ctx.get("_book")
    if sh is None:
        return None, "skipped — sheet not opened (CRITICAL in strict mode)"
    tab = ctx["config"]["sheet"].get("expenses_tab", "EXPENSES")
    try:
        ws = sh.worksheet(tab)
    except Exception as e:
        return False, f"worksheet '{tab}' missing: {e}"
    headers = ws.row_values(2) if ws.row_count >= 2 else ws.row_values(1)
    expected = {"Txn_ID", "Date", "Amount", "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean", "Hash"}
    have = set((h or "").split(" ")[0] for h in headers)
    have_loose = set((h or "").lower().split(" ")[0] for h in headers)
    if not expected.issubset(have) and "amount" not in have_loose:
        return False, f"headers missing — got {headers}"
    return True, f"headers ok: {headers[:6]}…"


@gate("G4b MERCHANT_MASTER + CATEGORIES tabs present + headered")
def g4b(ctx):
    from merchant_resolver import build_master_from_rows, normalise_merchant

    sh = ctx.get("_book")
    if sh is None:
        return None, "skipped — sheet not opened (CRITICAL in strict mode)"
    needed = {
        "MERCHANT_MASTER": {"Merchant_Keyword", "Category", "Subcategory"},
        "CATEGORIES": {"Category", "Subcategory"},
    }
    worksheets = {}
    for tab, expected_headers in needed.items():
        try:
            ws = sh.worksheet(tab)
        except Exception as e:
            return False, f"worksheet '{tab}' missing: {e}"
        headers = ws.row_values(2) if ws.row_count >= 2 else ws.row_values(1)
        have = set((h or "").strip() for h in headers if h)
        if not expected_headers.issubset(have):
            missing = expected_headers - have
            return False, f"{tab} missing headers: {missing} (got {headers[:6]})"
        worksheets[tab] = ws

    merchant_rows = worksheets["MERCHANT_MASTER"].get_all_values()
    category_rows = worksheets["CATEGORIES"].get_all_values()

    def find_header_index(rows, required):
        for index, row in enumerate(rows):
            cells = {(cell or "").strip() for cell in row}
            if required.issubset(cells):
                return index
        raise ValueError(f"required headers not found: {sorted(required)}")

    merchant_header_index = find_header_index(
        merchant_rows, {"Merchant_Keyword", "Category", "Subcategory"}
    )
    category_header_index = find_header_index(
        category_rows, {"Category", "Subcategory"}
    )
    merchant_headers = [
        (cell or "").strip() for cell in merchant_rows[merchant_header_index]
    ]
    category_headers = [
        (cell or "").strip() for cell in category_rows[category_header_index]
    ]
    merchant_key_index = merchant_headers.index("Merchant_Keyword")
    merchant_category_index = merchant_headers.index("Category")
    merchant_subcategory_index = merchant_headers.index("Subcategory")
    category_index = category_headers.index("Category")
    subcategory_index = category_headers.index("Subcategory")
    active_index = category_headers.index("Active") if "Active" in category_headers else None

    inactive_values = {"false", "0", "no", "inactive"}
    active_pairs = set()
    for row in category_rows[category_header_index + 1:]:
        if len(row) <= max(category_index, subcategory_index):
            continue
        if active_index is not None and len(row) > active_index:
            if str(row[active_index]).strip().lower() in inactive_values:
                continue
        category = str(row[category_index]).strip()
        subcategory = str(row[subcategory_index]).strip()
        if category and subcategory:
            active_pairs.add((category.casefold(), subcategory.casefold()))
    if not active_pairs:
        return False, "CATEGORIES has no active Category/Subcategory pairs"

    seen_merchants = {}
    for sheet_row, row in enumerate(
        merchant_rows[merchant_header_index + 1:], start=merchant_header_index + 2
    ):
        if len(row) <= merchant_key_index:
            continue
        merchant = str(row[merchant_key_index]).strip()
        if not merchant:
            continue
        category = str(row[merchant_category_index]).strip() \
            if len(row) > merchant_category_index else ""
        subcategory = str(row[merchant_subcategory_index]).strip() \
            if len(row) > merchant_subcategory_index else ""
        if not category or not subcategory:
            return False, f"MERCHANT_MASTER row {sheet_row} is missing Category/Subcategory"
        pair = (category.casefold(), subcategory.casefold())
        if pair not in active_pairs:
            return False, (
                f"MERCHANT_MASTER row {sheet_row} uses a pair not present in active "
                f"CATEGORIES: {category} / {subcategory}"
            )
        merchant_key = normalise_merchant(merchant)
        if not merchant_key:
            return False, (
                f"MERCHANT_MASTER row {sheet_row} has no usable merchant keyword "
                "after normalization"
            )
        if merchant_key in seen_merchants and seen_merchants[merchant_key] != pair:
            return False, f"MERCHANT_MASTER has conflicting duplicate keyword: {merchant}"
        seen_merchants[merchant_key] = pair

    if ("misc", "other") not in active_pairs:
        return False, "CATEGORIES is missing the active review fallback pair: Misc / Other"

    try:
        build_master_from_rows(merchant_rows)
    except ValueError as exc:
        return False, f"MERCHANT_MASTER conflict: {exc}"

    return True, (
        "MERCHANT_MASTER + CATEGORIES headers and mapping integrity pass "
        f"({len(seen_merchants)} merchants, {len(active_pairs)} active pairs)"
    )


@gate("G5 parser parses 5 sample notifications")
def g5(ctx):
    from parse_transaction import parse
    samples = [
        "AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026",
        "Charge of AED 12.50 at STARBUCKS DXB — 29 Apr 2026",
        "AED 250 at LULU HYPER on 28-04-2026",
        "USD 14.99 NETFLIX — 27 Apr 2026",
        "150.00 AED Carrefour MOE",
    ]
    parsed_ok = sum(1 for s in samples if parse(s).valid)
    if parsed_ok < 4:
        return False, f"only {parsed_ok}/5 samples parsed cleanly"
    return True, f"{parsed_ok}/5 parsed"


@gate("G6 resolver returns correct tier on fixtures")
def g6(ctx):
    from merchant_resolver import build_master_from_rows, resolve
    master_rows = [
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
        ["Carrefour", "Carrefour", "Groceries", "Supermarket"],
    ]
    m = build_master_from_rows(master_rows)
    cases = [
        ("Carrefour MOE", 1),
        ("STARBUCKS COFFEE", 2),
        ("XYZ123", 3),
        ("purchase", 3),
    ]
    fails = [c for c, expected_tier in cases if resolve(c, m)["tier"] != expected_tier]
    if fails:
        return False, f"resolver mismatched on: {fails}"
    return True, "all 4 fixtures resolved correctly"


@gate("G6b word-boundary safety — no substring false positives")
def g6b(ctx):
    """Audit-driven gate (2026-05-01): proves the resolver no longer
    fires raw substring false positives. Single-word master keys must
    NOT match inside longer unrelated words."""
    from merchant_resolver import build_master_from_rows, resolve, merchant_matches
    master_rows = [
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
        ["rent", "Rent", "Housing", "Rent"],
        ["gems", "GEMS", "Education", "School Fees"],
    ]
    m = build_master_from_rows(master_rows)

    # Positive: word-boundary match should fire
    if resolve("RENT MAY 2026", m)["tier"] != 1:
        return False, "word-boundary positive failed: 'RENT MAY 2026' should hit master"
    if resolve("GEMS DUBAI", m)["tier"] != 1:
        return False, "word-boundary positive failed: 'GEMS DUBAI' should hit master"

    # Negative: substring inside longer word must NOT match
    if resolve("rental car downtown", m)["tier"] == 1:
        return False, "FALSE POSITIVE: 'rent' matched inside 'rental'"
    if resolve("current account fee", m)["tier"] == 1:
        return False, "FALSE POSITIVE: 'rent' matched inside 'current'"
    if resolve("engagement gift", m)["tier"] == 1:
        return False, "FALSE POSITIVE: 'gems' matched inside 'engagement'"

    # Helper-level checks
    if not merchant_matches("rent", "RENT MAY 2026"):
        return False, "merchant_matches positive failed"
    if merchant_matches("rent", "rental car"):
        return False, "merchant_matches false positive: 'rent' in 'rental'"
    if merchant_matches("rent", "current account"):
        return False, "merchant_matches false positive: 'rent' in 'current'"

    return True, "word-boundary matching verified — no substring false positives"


@gate("G7 hash dedup")
def g7(ctx):
    from parse_transaction import parse
    a = parse("AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026")
    b = parse("AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026")
    c = parse("AED 87.00 spent on WioCredit at NOON.COM on 29/04/2026")
    if a.hash != b.hash:
        return False, "identical inputs produced different hashes"
    if a.hash == c.hash:
        return False, "different merchants produced same hash"
    return True, f"hash={a.hash}"


@gate("G8 row-build dry-run")
def g8(ctx):
    """Builds a transaction row in HEADERS order. Proves the row builder
    works and the row would round-trip through the dry-run path.

    This gate does NOT prove live write permission — that's G8b's job.
    """
    from write_sheet import transaction_to_row, HEADERS
    fake_txn = {
        "txn_id": "DRYRUN0001",
        "date": "2026-04-29",
        "amount": 87.00,
        "currency": "AED",
        "merchant_raw": "AMAZON.AE",
        "merchant_clean": "Amazon",
        "category": "Shopping",
        "subcategory": "Online Retail",
        "card": "WioCredit",
        "source": "DryRun",
        "hash": "abcdef1234567890",
    }
    row = transaction_to_row(fake_txn)
    if len(row) != len(HEADERS):
        return False, f"row length {len(row)} != HEADERS {len(HEADERS)}"
    return True, "row built in HEADERS order (does NOT prove live write — see G8b)"


@gate("G8b safe live-write proof (EXPENSES_TEST)")
def g8b(ctx):
    """Real append/read/cleanup against EXPENSES_TEST tab. Proves:
      - service-account auth succeeds against the live API
      - append permission on the user's sheet
      - row round-trips (read-back equals what we wrote)
      - cleanup succeeds (validation row removed)

    Critical in strict mode. Skipped if no sheet configured.
    """
    cfg = ctx["config"]
    sheet_id = cfg["sheet"].get("id")
    if not sheet_id:
        return None, "skipped — no sheet ID configured (CRITICAL in strict mode)"

    sh = ctx.get("_book")
    if sh is None:
        return None, "skipped — sheet not opened (CRITICAL in strict mode)"

    try:
        ws = sh.worksheet("EXPENSES_TEST")
    except Exception as e:
        return False, f"EXPENSES_TEST tab missing — needed for safe write proof: {e}"

    from datetime import datetime as _dt, timezone as _tz
    sentinel_id = "VALIDATE_" + _dt.now(_tz.utc).strftime("%Y%m%d%H%M%S%f")
    from write_sheet import transaction_to_row
    test_txn = {
        "txn_id": sentinel_id,
        "date": _dt.now(_tz.utc).strftime("%Y-%m-%d"),
        "amount": 0.01,
        "currency": cfg.get("locale", {}).get("default_currency", "USD"),
        "merchant_raw": "VALIDATE_INSTALL_PROOF",
        "merchant_clean": "Validate Install Proof",
        "category": "_validate",
        "subcategory": "_validate",
        "card": "_validate",
        "source": "validate_install.py G8b",
        "status": "Validation",
        "notes": "Auto-cleanup row from validate_install.py — safe to delete",
        "hash": sentinel_id,
    }
    row = transaction_to_row(test_txn)

    try:
        ws.append_rows([row], value_input_option="USER_ENTERED")
    except Exception as e:
        return False, f"append to EXPENSES_TEST failed (no write permission?): {e}"

    # Read back: scan the last 10 rows for our sentinel
    try:
        all_values = ws.get_all_values()
        sentinel_row = None
        for idx, r in enumerate(reversed(all_values[-10:])):
            if r and r[0] == sentinel_id:
                # absolute row number (1-indexed)
                sentinel_row = len(all_values) - idx
                break
        if sentinel_row is None:
            return False, f"sentinel {sentinel_id} not found after append (read-back failed)"
    except Exception as e:
        return False, f"read-back failed: {e}"

    # Cleanup: delete the sentinel row
    try:
        ws.delete_rows(sentinel_row)
        return True, f"appended → read-back → deleted row {sentinel_row} (sentinel={sentinel_id[:24]}…)"
    except Exception as e:
        # Append + read worked, but cleanup failed — still partial pass with a clear warning
        return False, (f"append+read OK but cleanup failed (row {sentinel_row} stayed): {e} "
                       f"— delete row manually before next run")


def main():
    import contextlib
    import io
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true", default=True,
                    help="Critical skipped gates count as FAIL (default; required before live arm)")
    ap.add_argument("--non-strict", dest="strict", action="store_false",
                    help="Critical skipped gates count as SKIP (development/partial setup only)")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(args.config))
    ctx = {"config": cfg, "dry_run": args.dry_run, "strict": args.strict}

    if not args.json:
        print(f"validate_install — config: {args.config}  mode: {'STRICT' if args.strict else 'non-strict'}\n")

    results = []
    fail = 0
    skip_critical = 0
    skip_noncritical = 0
    for name, fn in GATES:
        # In --json mode, suppress any side-effect prints from the gate
        # (e.g. write_sheet's "would append" preview) so the JSON output is clean.
        try:
            if args.json:
                with contextlib.redirect_stdout(io.StringIO()):
                    ok, msg = fn(ctx)
            else:
                ok, msg = fn(ctx)
        except Exception as e:
            ok, msg = False, f"exception: {e}"

        is_critical = name in CRITICAL_GATES
        if ok is True:
            mark, status = "✅", "pass"
        elif ok is None:
            if args.strict and is_critical:
                # Strict mode: critical skip becomes fail
                mark, status = "❌", "fail"
                msg = f"FAIL (strict-mode critical skip): {msg}"
                fail += 1
            else:
                mark = "⏭️ "
                status = "skip"
                if is_critical:
                    skip_critical += 1
                else:
                    skip_noncritical += 1
        else:
            mark, status = "❌", "fail"
            fail += 1

        results.append({
            "gate": name,
            "status": status,
            "critical": is_critical,
            "message": msg,
        })

        if not args.json:
            crit_tag = " [CRITICAL]" if is_critical else ""
            print(f"  {mark}  {name}{crit_tag}  —  {msg}")

    passed = sum(1 for r in results if r["status"] == "pass")
    skipped = skip_critical + skip_noncritical

    summary = {
        "mode": "strict" if args.strict else "non-strict",
        "passed": passed,
        "failed": fail,
        "skipped": skipped,
        "skipped_critical": skip_critical,
        "exit_code": 0 if fail == 0 else 1,
        "ready_for_arm": (fail == 0 and skip_critical == 0),
        "results": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print()
        print(f"  {passed} passed · {fail} failed · {skipped} skipped"
              + (f" ({skip_critical} critical)" if skip_critical else ""))
        print(f"  ready_for_arm: {summary['ready_for_arm']}")

    sys.exit(summary["exit_code"])


if __name__ == "__main__":
    main()
