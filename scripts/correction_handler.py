#!/usr/bin/env python3
"""correction_handler.py — turn a free-form correction message into a ledger update.

Triggered by the confirmation adapter when the user replies to a confirmation
message ("change to Groceries", "change Noon to Groceries / Online Grocery", etc.).

Two correction shapes:
  1. "change to <Category> [/ <Subcategory>]"
       → Updates ONLY the most recent confirmed txn (passed in as --txn-id).
       → Updates MERCHANT_MASTER for that merchant so future txns auto-route.
  2. "change <Merchant> to <Category> [/ <Subcategory>]"
       → Adds/updates MERCHANT_MASTER for the named merchant.
       → Re-categorises ALL prior EXPENSES rows matching that merchant.

Safety guards (post-2026-05-01 audit fix):
  - Bulk recategorise (named-merchant scope) DEFAULTS to dry-run preview.
    Caller must pass --confirm-bulk to actually mutate rows.
  - MERCHANT_MASTER conflict detection: if the merchant already has a
    different category/subcategory, the change is REFUSED unless caller
    passes --allow-overwrite. Last-txn-only edits never touch master in
    conflict cases (only the single row).
  - Bulk match uses word-boundary phrase matching (`merchant_matches`),
    not raw substring. "rent" no longer matches "rental" or "current".
  - Every applied change is appended to the audit log at
    `~/.expense-bookkeeper/state/correction_audit.log` (JSONL).

Idempotent. Re-running the same correction is a no-op (rows already correct).

Usage:
  python3 correction_handler.py --config <config.yaml> --txn-id <TXN_ID> \\
      --message "change to Groceries / Online Grocery"

  # Bulk preview (default, safe):
  python3 correction_handler.py --config <config.yaml> \\
      --message "change Noon to Shopping / Online Retail"

  # Bulk apply (requires explicit --confirm-bulk):
  python3 correction_handler.py --config <config.yaml> \\
      --message "change Noon to Shopping / Online Retail" --confirm-bulk

  # Override an existing master mapping:
  python3 correction_handler.py --config <config.yaml> \\
      --message "change Spinneys to Groceries / Online" \\
      --confirm-bulk --allow-overwrite
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import gspread
import yaml
from google.oauth2.service_account import Credentials

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from adaptive_categories import AdaptiveCategoryStore
from merchant_resolver import merchant_matches  # word-boundary helper

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

AUDIT_LOG_DEFAULT = Path.home() / ".expense-bookkeeper" / "state" / "correction_audit.log"


# ── Correction parsing ─────────────────────────────────────────────────────

_RE_NAMED_MERCHANT = re.compile(
    r"^\s*change\s+(?P<merchant>[\w\s.&'\-]+?)\s+to\s+(?P<cat>[\w\s&'\-]+?)"
    r"(?:\s*/\s*(?P<sub>[\w\s&'\-]+))?\s*$",
    re.IGNORECASE,
)
_RE_LAST_TXN = re.compile(
    r"^\s*change\s+to\s+(?P<cat>[\w\s&'\-]+?)"
    r"(?:\s*/\s*(?P<sub>[\w\s&'\-]+))?\s*$",
    re.IGNORECASE,
)


def parse_correction(message: str) -> dict | None:
    """Return parsed correction dict or None if message isn't a correction.

    Tries named-merchant first (more specific), then last-txn fallback.
    """
    m = _RE_NAMED_MERCHANT.match(message)
    if m and m.group("merchant").lower() != "to":
        return {
            "kind": "named_merchant",
            "merchant": m.group("merchant").strip(),
            "category": m.group("cat").strip(),
            "subcategory": (m.group("sub") or "").strip(),
        }
    m = _RE_LAST_TXN.match(message)
    if m:
        return {
            "kind": "last_txn",
            "category": m.group("cat").strip(),
            "subcategory": (m.group("sub") or "").strip(),
        }
    return None


# ── Audit log ─────────────────────────────────────────────────────────────

def _audit_path(cfg: dict) -> Path:
    """Resolve audit log path. Prefers config-supplied state dir; falls back
    to ~/.expense-bookkeeper/state/correction_audit.log."""
    state_dir_str = cfg.get("metadata", {}).get("state_dir")
    if state_dir_str:
        p = Path(state_dir_str).expanduser() / "correction_audit.log"
    else:
        p = AUDIT_LOG_DEFAULT
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _audit(cfg: dict, entry: dict) -> None:
    """Append a JSONL audit entry. Never raises; audit failures are logged
    to stderr but never block the operation."""
    try:
        path = _audit_path(cfg)
        entry = {**entry, "ts": datetime.now(timezone.utc).isoformat() + "Z"}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        os.chmod(path, 0o600)
    except Exception as e:
        print(f"correction_handler: audit write failed: {e}", file=sys.stderr)


def _record_adaptive_learning(cfg: dict, merchant: str, category: str,
                              subcategory: str, txn_id: str = "") -> dict | None:
    """Mirror an applied correction into local adaptive state when enabled."""
    adaptive_cfg = cfg.get("categorization", {}).get("adaptive", {})
    if not adaptive_cfg.get("enabled", False) or not merchant:
        return None
    state_path = adaptive_cfg.get("state_path") or "~/.expense-bookkeeper/state/adaptive_categories.json"
    try:
        store = AdaptiveCategoryStore(state_path)
        return store.learn_confirmed(merchant, category, subcategory, source_txn_id=txn_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _audit(cfg, {"op": "adaptive_learning.failed", "error": type(exc).__name__})
        return {"action": "failed", "reason": type(exc).__name__}


# ── Sheet helpers ──────────────────────────────────────────────────────────

def _open_sheet(cfg: dict):
    sa = cfg["sheet"]["service_account_path"]
    creds = Credentials.from_service_account_file(str(Path(sa).expanduser()), scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(cfg["sheet"]["id"])


def _find_col(headers: list[str], name: str) -> int:
    """1-indexed column number; raises KeyError if missing."""
    return headers.index(name) + 1


def validate_taxonomy_pair(sh, category: str, subcategory: str) -> dict:
    """Resolve a proposed pair against active CATEGORIES rows.

    Corrections are an input boundary, so they must not create a new spelling,
    category, or subcategory by accident. Matching is case-insensitive, while
    the canonical Sheet spelling is returned for the actual write.
    """
    proposed_category = (category or "").strip()
    proposed_subcategory = (subcategory or "").strip()
    try:
        rows = sh.worksheet("CATEGORIES").get_all_values()
    except Exception as exc:
        return {
            "valid": False,
            "reason": "categories_unavailable",
            "detail": type(exc).__name__,
            "proposed": {
                "category": proposed_category,
                "subcategory": proposed_subcategory,
            },
        }

    header_index = None
    category_index = subcategory_index = active_index = None
    for index, row in enumerate(rows):
        normalized = [(cell or "").strip().lower() for cell in row]
        if "category" in normalized and "subcategory" in normalized:
            header_index = index
            category_index = normalized.index("category")
            subcategory_index = normalized.index("subcategory")
            active_index = normalized.index("active") if "active" in normalized else None
            break
    if header_index is None or category_index is None or subcategory_index is None:
        return {
            "valid": False,
            "reason": "categories_headers_missing",
            "proposed": {
                "category": proposed_category,
                "subcategory": proposed_subcategory,
            },
        }

    active_pairs: list[tuple[str, str]] = []
    inactive_values = {"false", "0", "no", "inactive"}
    for row in rows[header_index + 1:]:
        if len(row) <= max(category_index, subcategory_index):
            continue
        if active_index is not None and len(row) > active_index:
            if str(row[active_index]).strip().lower() in inactive_values:
                continue
        canonical_category = str(row[category_index]).strip()
        canonical_subcategory = str(row[subcategory_index]).strip()
        if canonical_category and canonical_subcategory:
            active_pairs.append((canonical_category, canonical_subcategory))

    for canonical_category, canonical_subcategory in active_pairs:
        if (
            canonical_category.casefold() == proposed_category.casefold()
            and canonical_subcategory.casefold() == proposed_subcategory.casefold()
        ):
            return {
                "valid": True,
                "category": canonical_category,
                "subcategory": canonical_subcategory,
            }

    valid_subcategories = sorted({
        sub for cat, sub in active_pairs
        if cat.casefold() == proposed_category.casefold()
    })
    return {
        "valid": False,
        "reason": "taxonomy_pair_not_found",
        "proposed": {
            "category": proposed_category,
            "subcategory": proposed_subcategory,
        },
        "valid_subcategories": valid_subcategories[:20],
    }


# ── Correction application ────────────────────────────────────────────────

def update_merchant_master(sh, merchant_keyword: str, category: str, subcategory: str,
                           cfg: dict, dry_run: bool = False,
                           allow_overwrite: bool = False) -> dict:
    """Add or update MERCHANT_MASTER row for this merchant.

    Match logic: case-insensitive equality on Merchant_Keyword. If row exists
    with the SAME category/subcategory → no-op. If row exists with DIFFERENT
    category/subcategory → REFUSED unless allow_overwrite=True (returns
    action='conflict_refused' with details so caller can prompt user).
    """
    ws = sh.worksheet("MERCHANT_MASTER")
    rows = ws.get_all_values()
    if len(rows) < 2:
        # Empty sheet
        if dry_run:
            return {"action": "would_append", "merchant": merchant_keyword,
                    "category": category, "subcategory": subcategory}
        ws.append_row(
            [merchant_keyword, merchant_keyword, category, subcategory, "", date.today().isoformat()],
            value_input_option="USER_ENTERED",
        )
        result = {"action": "appended", "merchant": merchant_keyword,
                  "category": category, "subcategory": subcategory}
        _audit(cfg, {"op": "merchant_master.append", **result})
        return result

    headers = rows[1]
    col_keyword = _find_col(headers, "Merchant_Keyword")
    col_clean   = _find_col(headers, "Merchant_Clean")
    col_cat     = _find_col(headers, "Category")
    col_sub     = _find_col(headers, "Subcategory")
    col_updated = _find_col(headers, "Last_Updated")

    target_lower = merchant_keyword.lower()
    for i, row in enumerate(rows[2:], start=3):
        if len(row) > col_keyword - 1 and row[col_keyword - 1].strip().lower() == target_lower:
            existing_cat = row[col_cat - 1].strip() if len(row) > col_cat - 1 else ""
            existing_sub = row[col_sub - 1].strip() if len(row) > col_sub - 1 else ""

            if existing_cat == category and existing_sub == subcategory:
                return {"action": "noop_already_set", "merchant": merchant_keyword, "row": i}

            # Conflict — different category/subcategory already set
            if not allow_overwrite:
                return {
                    "action": "conflict_refused",
                    "merchant": merchant_keyword,
                    "row": i,
                    "existing": {"category": existing_cat, "subcategory": existing_sub},
                    "proposed": {"category": category, "subcategory": subcategory},
                    "hint": "Re-run with --allow-overwrite to replace, or use last-txn correction (--txn-id) to fix only this transaction.",
                }

            if dry_run:
                return {
                    "action": "would_overwrite",
                    "merchant": merchant_keyword,
                    "row": i,
                    "existing": {"category": existing_cat, "subcategory": existing_sub},
                    "proposed": {"category": category, "subcategory": subcategory},
                }
            ws.update_cell(i, col_cat, category)
            ws.update_cell(i, col_sub, subcategory)
            ws.update_cell(i, col_updated, date.today().isoformat())
            result = {
                "action": "overwritten",
                "merchant": merchant_keyword,
                "row": i,
                "previous": {"category": existing_cat, "subcategory": existing_sub},
                "current": {"category": category, "subcategory": subcategory},
            }
            _audit(cfg, {"op": "merchant_master.overwrite", **result})
            return result

    # Not found — append
    if dry_run:
        return {"action": "would_append", "merchant": merchant_keyword,
                "category": category, "subcategory": subcategory}
    ws.append_row(
        [merchant_keyword, merchant_keyword, category, subcategory, "", date.today().isoformat()],
        value_input_option="USER_ENTERED",
    )
    result = {"action": "appended", "merchant": merchant_keyword,
              "category": category, "subcategory": subcategory}
    _audit(cfg, {"op": "merchant_master.append", **result})
    return result


def recategorise_expenses(sh, merchant_keyword: str, category: str, subcategory: str,
                          cfg: dict, dry_run: bool = True) -> dict:
    """Update Category + Subcategory on all EXPENSES rows whose Merchant_Raw
    or Merchant_Clean matches the merchant keyword by **word-boundary phrase**
    (NOT raw substring).

    Defaults to dry_run=True. Caller must explicitly pass dry_run=False to
    mutate. The dry-run preview returns the list of affected row numbers so
    the caller can show the user what would change before confirming.
    """
    ws = sh.worksheet("EXPENSES")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {"updated": 0, "scanned": 0, "rows": []}

    headers = rows[1]
    col_raw   = _find_col(headers, "Merchant_Raw")
    col_clean = _find_col(headers, "Merchant_Clean")
    col_cat   = _find_col(headers, "Category")
    col_sub   = _find_col(headers, "Subcategory")
    col_status = _find_col(headers, "Status") if "Status" in headers else None
    col_review = _find_col(headers, "Review_Reason") if "Review_Reason" in headers else None
    col_id_idx = headers.index("Txn_ID") if "Txn_ID" in headers else None

    affected = []
    for i, row in enumerate(rows[2:], start=3):
        if len(row) <= max(col_raw, col_clean) - 1:
            continue
        raw   = row[col_raw - 1]
        clean = row[col_clean - 1]
        # Word-boundary match against either raw or cleaned merchant text.
        if not (merchant_matches(merchant_keyword, raw) or
                merchant_matches(merchant_keyword, clean)):
            continue
        existing_cat = row[col_cat - 1] if len(row) > col_cat - 1 else ""
        existing_sub = row[col_sub - 1] if len(row) > col_sub - 1 else ""
        existing_status = (
            row[col_status - 1].strip()
            if col_status is not None and len(row) > col_status - 1 else ""
        )
        if (existing_cat.strip() == category and existing_sub.strip() == subcategory
                and existing_status.casefold() != "review"):
            continue
        txn_id = row[col_id_idx] if col_id_idx is not None and col_id_idx < len(row) else ""
        affected.append({
            "row": i,
            "txn_id": txn_id,
            "merchant_raw": raw,
            "merchant_clean": clean,
            "previous": {"category": existing_cat, "subcategory": existing_sub},
        })

    if dry_run:
        return {
            "updated": 0,
            "would_update": len(affected),
            "scanned": len(rows) - 2,
            "preview": affected,
            "rows": [a["row"] for a in affected],
        }

    for entry in affected:
        ws.update_cell(entry["row"], col_cat, category)
        ws.update_cell(entry["row"], col_sub, subcategory)
        if col_status is not None:
            ws.update_cell(entry["row"], col_status, "Confirmed")
        if col_review is not None:
            ws.update_cell(entry["row"], col_review, "")
        _audit(cfg, {
            "op": "expenses.recategorise",
            "row": entry["row"],
            "txn_id": entry["txn_id"],
            "merchant_raw": entry["merchant_raw"],
            "previous": entry["previous"],
            "current": {"category": category, "subcategory": subcategory},
            "match_kind": "word_boundary",
        })

    return {
        "updated": len(affected),
        "scanned": len(rows) - 2,
        "rows": [a["row"] for a in affected],
    }


def update_one_txn(sh, txn_id: str, category: str, subcategory: str,
                   cfg: dict, dry_run: bool = False) -> dict:
    """Update Category + Subcategory on the single EXPENSES row with this Txn_ID.
    Returns the merchant on that row so caller can also push to MERCHANT_MASTER."""
    ws = sh.worksheet("EXPENSES")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {"action": "txn_not_found"}
    headers = rows[1]
    col_id    = _find_col(headers, "Txn_ID")
    col_cat   = _find_col(headers, "Category")
    col_sub   = _find_col(headers, "Subcategory")
    col_clean = _find_col(headers, "Merchant_Clean")
    col_status = _find_col(headers, "Status") if "Status" in headers else None
    col_review = _find_col(headers, "Review_Reason") if "Review_Reason" in headers else None

    for i, row in enumerate(rows[2:], start=3):
        if len(row) > col_id - 1 and row[col_id - 1].strip() == txn_id:
            merchant = row[col_clean - 1] if len(row) > col_clean - 1 else ""
            existing_cat = row[col_cat - 1].strip() if len(row) > col_cat - 1 else ""
            existing_sub = row[col_sub - 1].strip() if len(row) > col_sub - 1 else ""
            existing_status = (
                row[col_status - 1].strip()
                if col_status is not None and len(row) > col_status - 1 else ""
            )
            if (existing_cat == category and existing_sub == subcategory
                    and existing_status.casefold() != "review"):
                return {"action": "noop_already_set", "row": i, "merchant": merchant}
            if dry_run:
                return {"action": "would_update", "row": i, "merchant": merchant,
                        "previous": {"category": existing_cat, "subcategory": existing_sub}}
            ws.update_cell(i, col_cat, category)
            ws.update_cell(i, col_sub, subcategory)
            if col_status is not None:
                ws.update_cell(i, col_status, "Confirmed")
            if col_review is not None:
                ws.update_cell(i, col_review, "")
            _audit(cfg, {
                "op": "expenses.update_one",
                "row": i,
                "txn_id": txn_id,
                "merchant": merchant,
                "previous": {"category": existing_cat, "subcategory": existing_sub},
                "current": {"category": category, "subcategory": subcategory},
            })
            return {"action": "updated", "row": i, "merchant": merchant}
    return {"action": "txn_not_found", "txn_id": txn_id}


# ── Main ───────────────────────────────────────────────────────────────────

def apply_correction(sh, parsed: dict, txn_id: str | None, cfg: dict,
                     dry_run: bool = False, confirm_bulk: bool = False,
                     allow_overwrite: bool = False) -> dict:
    """Apply correction with safety guards.

    For named_merchant scope (bulk): defaults to dry-run preview unless
    confirm_bulk=True. Master overwrites blocked unless allow_overwrite=True.
    """
    taxonomy = validate_taxonomy_pair(
        sh,
        parsed.get("category", ""),
        parsed.get("subcategory", ""),
    )
    if not taxonomy.get("valid"):
        return {
            "correction": parsed,
            "blocked": True,
            "reason": taxonomy.get("reason", "taxonomy_pair_not_found"),
            "taxonomy": taxonomy,
        }
    cat = taxonomy["category"]
    sub = taxonomy["subcategory"]

    if parsed["kind"] == "last_txn":
        if not txn_id:
            return {"error": "last-txn correction needs --txn-id (the txn the user is replying to)"}
        single = update_one_txn(sh, txn_id, cat, sub, cfg, dry_run=dry_run)
        if single.get("action") == "txn_not_found":
            return {"error": f"Txn_ID {txn_id} not found in EXPENSES"}
        merchant = single.get("merchant") or ""
        if merchant:
            master = update_merchant_master(sh, merchant, cat, sub, cfg,
                                            dry_run=dry_run,
                                            allow_overwrite=allow_overwrite)
        else:
            master = {"action": "skipped_no_merchant"}
        adaptive = None
        if not dry_run and master.get("action") != "conflict_refused":
            adaptive = _record_adaptive_learning(cfg, merchant, cat, sub, txn_id or "")
        return {"correction": parsed, "scope": "last_txn", "single": single,
                "master": master, "adaptive": adaptive}

    # named_merchant — bulk path. Default safety: preview only.
    merchant = parsed["merchant"]

    # Master conflict gate (always check first; never silently overwrite).
    master = update_merchant_master(sh, merchant, cat, sub, cfg,
                                    dry_run=True,  # always preview master first
                                    allow_overwrite=allow_overwrite)

    if master["action"] == "conflict_refused":
        return {
            "correction": parsed,
            "scope": "named_merchant",
            "master": master,
            "blocked": True,
            "reason": "merchant_master_conflict",
        }

    # Bulk preview is mandatory unless confirm_bulk=True.
    bulk = recategorise_expenses(sh, merchant, cat, sub, cfg, dry_run=True)

    if not confirm_bulk:
        # Return the preview without mutating anything.
        return {
            "correction": parsed,
            "scope": "named_merchant",
            "master": {**master, "action": master["action"], "applied": False},
            "bulk": bulk,
            "preview_only": True,
            "hint": "Re-run with --confirm-bulk to apply. Master + bulk will be written together.",
        }

    # Confirmed: apply master + bulk for real.
    master_applied = update_merchant_master(sh, merchant, cat, sub, cfg,
                                            dry_run=False,
                                            allow_overwrite=allow_overwrite)
    bulk_applied = recategorise_expenses(sh, merchant, cat, sub, cfg, dry_run=False)
    adaptive = _record_adaptive_learning(cfg, merchant, cat, sub)
    return {
        "correction": parsed,
        "scope": "named_merchant",
        "master": master_applied,
        "bulk": bulk_applied,
        "adaptive": adaptive,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--message", required=True, help="Free-form correction text from user reply")
    ap.add_argument("--txn-id", help="Txn_ID of the row the correction is replying to (for last_txn scope)")
    ap.add_argument("--dry-run", action="store_true", help="Preview only — never write")
    ap.add_argument("--confirm-bulk", action="store_true",
                    help="Required for named-merchant scope to actually write rows. "
                         "Without this flag, named-merchant corrections only preview.")
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="Required when MERCHANT_MASTER already has a different category/subcategory.")
    args = ap.parse_args()

    parsed = parse_correction(args.message)
    if not parsed:
        print(f"correction_handler: not a correction message: {args.message!r}", file=sys.stderr)
        print(f"  Supported shapes:", file=sys.stderr)
        print(f"    'change to <Category> [/ <Subcategory>]'", file=sys.stderr)
        print(f"    'change <Merchant> to <Category> [/ <Subcategory>]'", file=sys.stderr)
        sys.exit(2)

    cfg = yaml.safe_load(open(Path(args.config).expanduser()))
    sh = _open_sheet(cfg)
    result = apply_correction(
        sh, parsed, args.txn_id, cfg,
        dry_run=args.dry_run,
        confirm_bulk=args.confirm_bulk,
        allow_overwrite=args.allow_overwrite,
    )

    if "error" in result:
        print(f"correction_handler: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if result.get("blocked"):
        print(f"correction_handler: BLOCKED — {result['reason']}", file=sys.stderr)
        print(f"  master: {result['master']}", file=sys.stderr)
        sys.exit(3)

    print(f"correction_handler: {result['scope']} correction"
          + (" [DRY RUN]" if args.dry_run else "")
          + (" [PREVIEW ONLY — pass --confirm-bulk to apply]" if result.get("preview_only") else ""))
    if result["scope"] == "last_txn":
        print(f"  txn:      {result['single']}")
        print(f"  master:   {result['master']}")
    else:
        print(f"  master:   {result['master']}")
        bulk = result["bulk"]
        if "would_update" in bulk:
            print(f"  bulk:     {bulk['would_update']} rows WOULD be recategorised "
                  f"(scanned {bulk['scanned']}). Word-boundary match.")
            for entry in bulk["preview"][:10]:
                print(f"    row {entry['row']:>4} txn={entry['txn_id'] or '—'} "
                      f"merchant={entry['merchant_raw']!r} "
                      f"prev={entry['previous']['category']}/{entry['previous']['subcategory']}")
            if len(bulk["preview"]) > 10:
                print(f"    … and {len(bulk['preview']) - 10} more")
        else:
            print(f"  bulk:     {bulk['updated']} rows recategorised (scanned {bulk['scanned']})")


if __name__ == "__main__":
    main()
