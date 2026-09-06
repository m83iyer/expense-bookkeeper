#!/usr/bin/env python3
"""
recategorise_history.py — re-resolve historical EXPENSES rows against the
current MERCHANT_MASTER + keyword cues.

Use cases:
  - After installing a regional merchant pack: re-categorise old rows that
    were tier-3 or tier-2 before the pack landed.
  - After splitting/merging/renaming a category in CATEGORIES: re-resolve
    affected rows against the updated MERCHANT_MASTER.
  - After hand-editing MERCHANT_MASTER: propagate to history.

Safety guards (post-2026-05-01 audit):
  - DEFAULTS to dry-run preview. Caller must pass --confirm to mutate rows.
  - Refuses to apply >50 row changes without --confirm AND --large-batch flag.
  - Word-boundary matching only (uses merchant_resolver.merchant_matches).
  - Every proposed pair must exist in the active CATEGORIES taxonomy.
  - Every applied change is appended to the correction audit log.

Filters:
  --since YYYY-MM-DD       Only consider rows with Date >= this date.
  --until YYYY-MM-DD       Only consider rows with Date <= this date.
  --map "OLD=>NEW,X=>auto" Only consider rows whose current category is OLD.
                           NEW=auto re-runs the resolver. NEW=<literal>
                           sets category to that literal value (rename mode).

Usage:
  # Dry-run preview (default, safe):
  python3 recategorise_history.py --config <config.yaml> --since 2026-04-12

  # Apply changes after preview (small batch):
  python3 recategorise_history.py --config <config.yaml> --since 2026-04-12 --confirm

  # Apply >50 row changes (requires explicit large-batch flag):
  python3 recategorise_history.py --config <config.yaml> --since 2026-04-12 \\
      --confirm --large-batch

  # Rename category (literal map):
  python3 recategorise_history.py --config <config.yaml> \\
      --map "Food=>Groceries,Bills=>Utilities" --confirm

  # Re-resolve all rows currently categorised as "Food":
  python3 recategorise_history.py --config <config.yaml> \\
      --map "Food=>auto" --confirm
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import gspread
import yaml
from google.oauth2.service_account import Credentials

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from merchant_resolver import build_master_from_rows, resolve

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
LARGE_BATCH_THRESHOLD = 50
AUDIT_LOG_DEFAULT = Path.home() / ".expense-bookkeeper" / "state" / "correction_audit.log"


def _audit_path(cfg: dict) -> Path:
    state_dir_str = cfg.get("metadata", {}).get("state_dir")
    if state_dir_str:
        p = Path(state_dir_str).expanduser() / "correction_audit.log"
    else:
        p = AUDIT_LOG_DEFAULT
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _audit(cfg: dict, entry: dict) -> None:
    try:
        path = _audit_path(cfg)
        entry = {**entry, "ts": datetime.now(timezone.utc).isoformat() + "Z"}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"recategorise_history: audit write failed: {e}", file=sys.stderr)


def _open_sheet(cfg: dict):
    sa = cfg["sheet"]["service_account_path"]
    creds = Credentials.from_service_account_file(str(Path(sa).expanduser()), scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(cfg["sheet"]["id"])


def _parse_map(map_arg: str | None) -> dict:
    """Parse "OLD=>NEW,X=>auto" into {"OLD": "NEW", "X": "auto"}."""
    if not map_arg:
        return {}
    out = {}
    for chunk in map_arg.split(","):
        if "=>" not in chunk:
            continue
        k, v = chunk.split("=>", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {s}")


def _row_date(s: str) -> date | None:
    try:
        return _parse_date(s)
    except Exception:
        return None


def _active_taxonomy(sh) -> dict[tuple[str, str], tuple[str, str]]:
    """Return active taxonomy pairs keyed case-insensitively.

    The sheet's spelling remains canonical for writes. A missing or empty
    taxonomy is unsafe because historical re-categorisation must never invent
    category labels.
    """
    rows = sh.worksheet("CATEGORIES").get_all_values()
    required = {"Category", "Subcategory"}
    header_index = None
    for index, row in enumerate(rows):
        if required.issubset({str(cell).strip() for cell in row}):
            header_index = index
            break
    if header_index is None:
        raise RuntimeError("CATEGORIES headers missing: Category, Subcategory")

    headers = [str(cell).strip() for cell in rows[header_index]]
    category_index = headers.index("Category")
    subcategory_index = headers.index("Subcategory")
    active_index = headers.index("Active") if "Active" in headers else None
    inactive_values = {"false", "0", "no", "inactive"}

    active_pairs = {}
    for row in rows[header_index + 1:]:
        if len(row) <= max(category_index, subcategory_index):
            continue
        if active_index is not None and len(row) > active_index:
            if str(row[active_index]).strip().lower() in inactive_values:
                continue
        category = str(row[category_index]).strip()
        subcategory = str(row[subcategory_index]).strip()
        if category and subcategory:
            active_pairs[(category.casefold(), subcategory.casefold())] = (
                category,
                subcategory,
            )

    if not active_pairs:
        raise RuntimeError("CATEGORIES has no active Category/Subcategory pairs")
    return active_pairs


def plan_changes(sh, cfg: dict, since: date | None, until: date | None,
                 cat_map: dict) -> list[dict]:
    """Build the list of proposed row changes. No mutation."""
    ws = sh.worksheet("EXPENSES")
    rows = ws.get_all_values()
    if len(rows) < 3:
        return []

    headers = rows[1]

    def col_idx(name):
        try:
            return headers.index(name)
        except ValueError:
            return None

    i_id = col_idx("Txn_ID")
    i_date = col_idx("Date")
    i_cat = col_idx("Category")
    i_sub = col_idx("Subcategory")
    i_raw = col_idx("Merchant_Raw")
    i_clean = col_idx("Merchant_Clean")
    if None in (i_id, i_cat, i_sub, i_raw):
        raise RuntimeError("EXPENSES headers missing required columns (Txn_ID, Category, Subcategory, Merchant_Raw)")

    # Build resolver context from current MERCHANT_MASTER
    master_ws = sh.worksheet("MERCHANT_MASTER")
    master_rows = master_ws.get_all_values()
    master = build_master_from_rows(master_rows)
    active_taxonomy = _active_taxonomy(sh)

    plan: list[dict] = []
    for sheet_row, row in enumerate(rows[2:], start=3):
        if len(row) <= max(i_cat, i_sub, i_raw):
            continue

        existing_cat = (row[i_cat] or "").strip()
        existing_sub = (row[i_sub] or "").strip()
        merchant_raw = (row[i_raw] or "").strip()
        merchant_clean = (row[i_clean] if i_clean is not None and i_clean < len(row) else "").strip()
        txn_id = (row[i_id] or "").strip()
        row_d = _row_date(row[i_date] if i_date is not None and i_date < len(row) else "")

        # Apply --since / --until filters
        if since and row_d and row_d < since:
            continue
        if until and row_d and row_d > until:
            continue

        # Apply --map filter
        if cat_map:
            if existing_cat not in cat_map:
                continue
            target = cat_map[existing_cat]
            if target == "auto":
                resolved = resolve(merchant_raw or merchant_clean, master)
                new_cat = resolved["category"]
                new_sub = resolved["subcategory"]
                tier = resolved["tier"]
                source = "auto"
            else:
                new_cat = target
                new_sub = existing_sub  # literal rename keeps subcategory
                tier = None
                source = "rename"
        else:
            # No map filter: re-resolve every row
            resolved = resolve(merchant_raw or merchant_clean, master)
            new_cat = resolved["category"]
            new_sub = resolved["subcategory"]
            tier = resolved["tier"]
            source = "auto"

        if new_cat == existing_cat and new_sub == existing_sub:
            continue
        if not new_cat:
            # Skill refused to guess (tier 3) — don't blank existing data
            continue

        taxonomy_key = (str(new_cat).casefold(), str(new_sub).casefold())
        canonical_pair = active_taxonomy.get(taxonomy_key)
        if canonical_pair is None:
            raise RuntimeError(
                "Resolved pair is not active in CATEGORIES: "
                f"{new_cat} / {new_sub} (merchant={merchant_raw!r}, row={sheet_row})"
            )
        new_cat, new_sub = canonical_pair

        plan.append({
            "row": sheet_row,
            "txn_id": txn_id,
            "merchant_raw": merchant_raw,
            "previous": {"category": existing_cat, "subcategory": existing_sub},
            "proposed": {"category": new_cat, "subcategory": new_sub},
            "tier": tier,
            "source": source,
        })

    return plan


def apply_changes(sh, cfg: dict, plan: list[dict]) -> int:
    """Apply the planned changes. Audits each row."""
    ws = sh.worksheet("EXPENSES")
    rows = ws.get_all_values()
    headers = rows[1]
    col_cat = headers.index("Category") + 1
    col_sub = headers.index("Subcategory") + 1

    for entry in plan:
        ws.update_cell(entry["row"], col_cat, entry["proposed"]["category"])
        ws.update_cell(entry["row"], col_sub, entry["proposed"]["subcategory"])
        _audit(cfg, {
            "op": "expenses.recategorise_history",
            "row": entry["row"],
            "txn_id": entry["txn_id"],
            "merchant_raw": entry["merchant_raw"],
            "previous": entry["previous"],
            "current": entry["proposed"],
            "source": entry["source"],
        })
    return len(plan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--since", help="YYYY-MM-DD; only consider rows on/after this date")
    ap.add_argument("--until", help="YYYY-MM-DD; only consider rows on/before this date")
    ap.add_argument("--map", help='Category mapping: "OLD=>NEW,X=>auto" (NEW=auto re-runs resolver)')
    ap.add_argument("--confirm", action="store_true",
                    help="Actually apply changes. Without this flag, only previews.")
    ap.add_argument("--large-batch", action="store_true",
                    help=f"Required when applying >{LARGE_BATCH_THRESHOLD} row changes.")
    ap.add_argument("--json", action="store_true", help="Emit JSON output")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(Path(args.config).expanduser()))
    sh = _open_sheet(cfg)
    since = _parse_date(args.since) if args.since else None
    until = _parse_date(args.until) if args.until else None
    cat_map = _parse_map(args.map)

    plan = plan_changes(sh, cfg, since, until, cat_map)

    if not plan:
        msg = "No rows matched the filters or all rows already correct."
        print(json.dumps({"changed": 0, "preview_only": True, "message": msg}) if args.json else msg)
        sys.exit(0)

    if not args.confirm:
        # Dry-run preview
        if args.json:
            print(json.dumps({"changed": 0, "preview_only": True, "would_change": len(plan), "plan": plan[:50]}, indent=2))
        else:
            print(f"PREVIEW — {len(plan)} rows would change. Re-run with --confirm to apply.")
            for entry in plan[:25]:
                print(f"  row {entry['row']:>4} txn={entry['txn_id'] or '—':<20} "
                      f"merchant={entry['merchant_raw']!r:<40} "
                      f"{entry['previous']['category']}/{entry['previous']['subcategory']} "
                      f"-> {entry['proposed']['category']}/{entry['proposed']['subcategory']} "
                      f"({entry['source']})")
            if len(plan) > 25:
                print(f"  … and {len(plan) - 25} more")
        sys.exit(0)

    if len(plan) > LARGE_BATCH_THRESHOLD and not args.large_batch:
        msg = (f"REFUSED: {len(plan)} row changes exceed safety threshold "
               f"({LARGE_BATCH_THRESHOLD}). Re-run with --confirm AND --large-batch.")
        print(msg, file=sys.stderr)
        sys.exit(2)

    n = apply_changes(sh, cfg, plan)
    print(f"recategorise_history: applied {n} row changes. Audit at {_audit_path(cfg)}")


if __name__ == "__main__":
    main()
