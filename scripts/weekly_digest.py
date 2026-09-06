#!/usr/bin/env python3
"""weekly_digest.py — render last-7-days summary, push via confirmation adapter.

Two ways to invoke:
  - Scheduled: weekly via launchd / cron (recipe in templates/launchd/weekly_digest.plist.template)
  - On-demand: user replies "summary" or "digest" to a confirmation message;
    the confirmation adapter shells out to this script.

Output: a markdown digest covering the user's last 7 calendar days. Sections:
  - Total spend (count + amount)
  - Top 5 categories by spend
  - Top 5 merchants by frequency
  - Largest single transaction
  - Recurring entries posted in the window

Queued for the configured confirmation adapter (whatsapp_hermes / email_confirm).

Usage:
  python3 weekly_digest.py --config <config.yaml> [--days 7] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import gspread
import yaml
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _open_sheet(cfg: dict):
    sa = cfg["sheet"]["service_account_path"]
    creds = Credentials.from_service_account_file(str(Path(sa).expanduser()), scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(cfg["sheet"]["id"])


def _parse_date(s: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _parse_amount(s: str) -> float:
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def collect(sh, days: int = 7, today: date | None = None) -> dict:
    """Walk EXPENSES for the last N days; return aggregates."""
    today = today or date.today()
    cutoff = today - timedelta(days=days - 1)

    ws = sh.worksheet("EXPENSES")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {"window_start": cutoff, "window_end": today, "count": 0, "total": 0.0}

    headers = rows[1]
    def col(h: str) -> int:
        try: return headers.index(h)
        except ValueError: return -1
    c_date    = col("Date")
    c_amount  = col("Amount")
    c_curr    = col("Currency")
    c_cat     = col("Category")
    c_sub     = col("Subcategory")
    c_merch   = col("Merchant_Clean")
    c_card    = col("Card_Used")
    c_source  = col("Source")
    c_status  = col("Status")

    in_window = []
    recurring_in_window = []
    largest = None
    cat_totals: dict[str, float] = defaultdict(float)
    merchant_count: Counter = Counter()
    currency_seen = ""

    for row in rows[2:]:
        if c_date < 0 or len(row) <= c_date:
            continue
        d = _parse_date(row[c_date])
        if not d or d < cutoff or d > today:
            continue
        # Skip rows under review (not yet confirmed)
        if c_status >= 0 and len(row) > c_status and row[c_status].strip() == "Review":
            continue
        amt = _parse_amount(row[c_amount]) if c_amount >= 0 and len(row) > c_amount else 0.0
        cat = row[c_cat].strip() if c_cat >= 0 and len(row) > c_cat else ""
        sub = row[c_sub].strip() if c_sub >= 0 and len(row) > c_sub else ""
        merchant = row[c_merch].strip() if c_merch >= 0 and len(row) > c_merch else ""
        card = row[c_card].strip() if c_card >= 0 and len(row) > c_card else ""
        source = row[c_source].strip() if c_source >= 0 and len(row) > c_source else ""
        currency = row[c_curr].strip() if c_curr >= 0 and len(row) > c_curr else ""

        in_window.append({"date": d, "amount": amt, "category": cat, "subcategory": sub,
                          "merchant": merchant, "card": card, "source": source})
        if currency and not currency_seen:
            currency_seen = currency
        if cat:
            cat_totals[f"{cat}{(' / ' + sub) if sub else ''}"] += amt
        if merchant:
            merchant_count[merchant] += 1
        if largest is None or amt > largest["amount"]:
            largest = {"merchant": merchant, "amount": amt, "category": cat, "date": d}
        if source.lower() == "recurring":
            recurring_in_window.append({"merchant": merchant, "amount": amt, "date": d})

    total = sum(t["amount"] for t in in_window)
    top_cats = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_merchants = merchant_count.most_common(5)

    return {
        "window_start": cutoff,
        "window_end": today,
        "count": len(in_window),
        "total": total,
        "currency": currency_seen or "",
        "top_categories": top_cats,
        "top_merchants": top_merchants,
        "largest": largest,
        "recurring": recurring_in_window,
    }


def render_markdown(data: dict) -> str:
    cur = data.get("currency", "")
    cur_str = f"{cur} " if cur else ""
    win = f"{data['window_start'].strftime('%a %d %b')} → {data['window_end'].strftime('%a %d %b')}"

    lines: list[str] = []
    lines.append(f"*Weekly digest · {win}*")
    lines.append("")
    if data["count"] == 0:
        lines.append("No transactions in this window.")
        return "\n".join(lines)

    lines.append(f"*{data['count']} transactions · {cur_str}{data['total']:,.2f} total*")
    lines.append("")

    if data["top_categories"]:
        lines.append("*Top categories*")
        for label, amt in data["top_categories"]:
            lines.append(f"  • {label} — {cur_str}{amt:,.2f}")
        lines.append("")

    if data["top_merchants"]:
        lines.append("*Most frequent merchants*")
        for merchant, n in data["top_merchants"]:
            lines.append(f"  • {merchant} ×{n}")
        lines.append("")

    if data["largest"]:
        lg = data["largest"]
        lines.append(
            f"*Largest:* {lg['merchant']} — {cur_str}{lg['amount']:,.2f} "
            f"({lg['category']}, {lg['date'].strftime('%a %d %b')})"
        )
        lines.append("")

    if data["recurring"]:
        lines.append(f"*Recurring posted ({len(data['recurring'])}):*")
        for r in data["recurring"]:
            lines.append(f"  • {r['merchant']} — {cur_str}{r['amount']:,.2f}")

    return "\n".join(lines).rstrip()


def push(cfg: dict, body: str, dry_run: bool = False) -> dict:
    """Send digest via the user's configured confirmation adapter.
    Each adapter contract: emit a 'message' string. This wrapper picks
    the adapter at user_config.confirmation.adapter and shells out to
    its emitter — adapter authors expose a `send_message(body)` recipe
    in their .md docs. For v1 we support email_confirm and whatsapp_hermes
    as the two emitters; otherwise we print to stdout for the user to forward.
    """
    adapter = (cfg.get("confirmation", {}) or {}).get("adapter", "")
    if dry_run or adapter in ("", "none"):
        return {"adapter": adapter or "stdout", "body": body, "sent": False, "dry_run": True}

    # The skill ships adapter recipes (.md). Actual push integration is per-user,
    # because each adapter has different auth (Gmail SMTP / Hermes target / etc).
    # We write the digest to a known queue file; the confirmation adapter watches
    # this file and emits. This keeps the skill core decoupled from delivery auth.
    queue = Path.home() / ".expense-bookkeeper" / "queue" / "digest.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(body + "\n")
    return {"adapter": adapter, "body_path": str(queue), "sent": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--date", help="Override 'today' as YYYY-MM-DD (testing)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print-only", action="store_true",
                    help="Print digest to stdout, skip adapter push")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(Path(args.config).expanduser()))
    sh = _open_sheet(cfg)
    today = date.fromisoformat(args.date) if args.date else None
    data = collect(sh, days=args.days, today=today)
    body = render_markdown(data)

    if args.print_only or args.dry_run:
        print(body)
        if args.dry_run:
            print(f"\n[DRY RUN — would push via {cfg.get('confirmation', {}).get('adapter', 'stdout')}]")
        return

    result = push(cfg, body)
    print(f"weekly_digest: queued at {result.get('body_path', '?')} for adapter={result['adapter']}")
    print(f"  txns_in_window: {data['count']}  total: {data.get('currency','')} {data['total']:,.2f}")


if __name__ == "__main__":
    main()
