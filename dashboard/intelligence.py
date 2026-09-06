"""Pure deterministic analytics for the Moneta dashboard."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable


def month_key(label: str) -> tuple[int, int]:
    value = datetime.strptime(label, "%b-%Y")
    return value.year, value.month


def month_label(year: int, month: int) -> str:
    return datetime(year, month, 1).strftime("%b-%Y")


def shift_month(label: str, amount: int) -> str:
    year, month = month_key(label)
    index = year * 12 + month - 1 + amount
    return month_label(index // 12, index % 12 + 1)


def pct_change(current: float, previous: float, complete: bool = True) -> float | None:
    return round((current - previous) / previous * 100, 1) if complete and previous else None


def month_sequence(end: str, count: int) -> list[str]:
    count = max(1, min(int(count), 24))
    return [shift_month(end, offset) for offset in range(-count + 1, 1)]


def period_label(labels: list[str]) -> str:
    if not labels:
        return "No period"
    readable = [datetime.strptime(label, "%b-%Y").strftime("%b %Y") for label in labels]
    return readable[0] if len(readable) == 1 else f"{readable[0]} to {readable[-1]}"


def _selected(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split("|") if item.strip()}


def _matches(item: dict[str, Any], categories: set[str], subcategories: set[str], merchants: set[str]) -> bool:
    return (
        (not categories or item.get("category") in categories)
        and (not subcategories or item.get("subcategory") in subcategories)
        and (not merchants or item.get("merchant_clean") in merchants)
    )


def _sum(rows: Iterable[dict[str, Any]]) -> float:
    return sum(float(item.get("amount") or 0) for item in rows)


def _money_text(value: float, currency: str) -> str:
    return f"{currency} {abs(value):,.0f}"


def _driver_id(path: list[str]) -> str:
    return "driver-" + hashlib.sha1("\x1f".join(path).encode("utf-8")).hexdigest()[:12]


def _driver_tree(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    *,
    factor: float,
    total: float,
    baseline_complete: bool,
) -> list[dict[str, Any]]:
    fields = (("category", "category"), ("subcategory", "subcategory"), ("merchant_clean", "merchant"))

    def build(now: list[dict[str, Any]], before: list[dict[str, Any]], depth: int, path: list[str]) -> list[dict[str, Any]]:
        field, level = fields[depth]
        names = sorted(
            {str(item.get(field) or "Unspecified") for item in now + before},
            key=lambda name: _sum(item for item in now if str(item.get(field) or "Unspecified") == name),
            reverse=True,
        )
        output = []
        for name in names:
            now_rows = [item for item in now if str(item.get(field) or "Unspecified") == name]
            before_rows = [item for item in before if str(item.get(field) or "Unspecified") == name]
            current_base, previous_base = _sum(now_rows), _sum(before_rows)
            node_path = [*path, name]
            node = {
                "id": _driver_id(node_path),
                "name": name,
                "level": level,
                "path": node_path,
                "current": round(current_base * factor, 2),
                "previous": round(previous_base * factor, 2),
                "delta": round((current_base - previous_base) * factor, 2),
                "pct": pct_change(current_base, previous_base, baseline_complete),
                "share": round(current_base / total * 100, 1) if total else 0,
                "transactions": len(now_rows),
                "previous_transactions": len(before_rows),
                "children": [],
            }
            if depth + 1 < len(fields):
                node["children"] = build(now_rows, before_rows, depth + 1, node_path)
            output.append(node)
        return output

    return build(current_rows, previous_rows, 0, [])


def build_analytics(
    ledger: list[dict[str, Any]],
    metadata: dict[str, str],
    *,
    selected_month: str = "",
    range_months: int = 3,
    category: str = "",
    subcategory: str = "",
    merchant: str = "",
    comparison: str = "previous",
    fx: dict[str, Any],
    cash_entry_enabled: bool = False,
    demo_mode: bool = False,
) -> dict[str, Any]:
    factor = float(fx["rate"])
    currency = str(fx["quote"])
    months = sorted({str(item["month_year"]) for item in ledger}, key=month_key)
    categories = sorted({str(item.get("category") or "Unspecified") for item in ledger})
    taxonomy = {
        name: sorted({str(item.get("subcategory") or "Unspecified") for item in ledger if item.get("category") == name})
        for name in categories
    }
    category_set, subcategory_set, merchant_set = _selected(category), _selected(subcategory), _selected(merchant)
    eligible_subcategories = sorted({
        str(item.get("subcategory") or "Unspecified") for item in ledger
        if not category_set or item.get("category") in category_set
    })
    eligible_merchants = sorted({
        str(item.get("merchant_clean") or "Unspecified") for item in ledger
        if _matches(item, category_set, subcategory_set, set())
    })
    base_meta = {
        "months": list(reversed(months)),
        "categories": categories,
        "taxonomy": taxonomy,
        "subcategories": eligible_subcategories,
        "merchants": eligible_merchants,
        "category": "|".join(sorted(category_set)),
        "subcategory": "|".join(sorted(subcategory_set)),
        "merchant": "|".join(sorted(merchant_set)),
        "range_months": max(1, min(int(range_months), 24)),
        "comparison": comparison if comparison in {"previous", "year"} else "previous",
        "currency": currency,
        "base_currency": fx["base"],
        "available_currencies": fx["available"],
        "fx_as_of": fx.get("as_of"),
        "fx_source": fx.get("source"),
        "fx_source_url": fx.get("source_url"),
        "fx_mode": fx.get("mode"),
        "last_updated": metadata.get("synced_at", "Not synced"),
        "cash_entry_enabled": cash_entry_enabled,
        "demo_mode": demo_mode,
    }
    if not months:
        return {
            "meta": {**base_meta, "selected_month": "", "period_label": "No transactions", "scope_label": "All spending",
                     "comparison_label": "Comparison unavailable", "previous_period_label": "No baseline",
                     "baseline_complete": False, "missing_baseline_months": []},
            "kpis": {"period": {"value": 0, "previous": 0, "change_pct": None},
                     "monthly_average": {"value": 0, "previous": 0, "change_pct": None},
                     "year": {"value": 0, "previous": 0, "change_pct": None},
                     "transactions": 0, "daily_average": 0},
            "trend": [], "driver_summary": {"current": 0, "previous": 0, "delta": 0, "pct": None,
                                                "transactions": 0, "previous_transactions": 0},
            "driver_rows": [], "insights": [{"tone": "neutral", "title": "No confirmed expenses yet",
                                                  "body": "Sync a ledger to begin the analysis."}], "transactions": [],
        }

    current = selected_month if selected_month in months else months[-1]
    window = max(1, min(int(range_months), 24))
    current_months = month_sequence(current, window)
    comparison_mode = comparison if comparison in {"previous", "year"} else "previous"
    previous_months = (
        [shift_month(label, -12) for label in current_months]
        if comparison_mode == "year"
        else [shift_month(label, -window) for label in current_months]
    )
    observed = set(months)
    missing_baseline = [label for label in previous_months if label not in observed]
    baseline_complete = not missing_baseline
    scoped = [item for item in ledger if _matches(item, category_set, subcategory_set, merchant_set)]
    current_rows = [item for item in scoped if item["month_year"] in set(current_months)]
    previous_rows = [item for item in scoped if item["month_year"] in set(previous_months)]
    current_base, previous_base = _sum(current_rows), _sum(previous_rows)
    current_value, previous_value = current_base * factor, previous_base * factor
    day_count = len({str(item.get("date")) for item in current_rows})
    yearly_months = [shift_month(label, -12) for label in current_months]
    yearly_complete = all(label in observed for label in yearly_months)
    yearly_rows = [item for item in scoped if item["month_year"] in set(yearly_months)]
    yearly_base = _sum(yearly_rows)

    trend_months = month_sequence(current, max(12, window))
    monthly: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for item in scoped:
        monthly[item["month_year"]] += float(item["amount"])
        counts[item["month_year"]] += 1
    trend = []
    for label in trend_months:
        comparison_label_for_month = shift_month(label, -12 if comparison_mode == "year" else -window)
        trend.append({
            "month": label,
            "amount": round(monthly[label] * factor, 2),
            "comparison_amount": round(monthly[comparison_label_for_month] * factor, 2)
            if comparison_label_for_month in observed else None,
            "transactions": counts[label],
        })

    tree = _driver_tree(
        current_rows, previous_rows, factor=factor, total=current_base, baseline_complete=baseline_complete
    )
    summary = {
        "current": round(current_value, 2),
        "previous": round(previous_value, 2),
        "delta": round(current_value - previous_value, 2),
        "pct": pct_change(current_base, previous_base, baseline_complete),
        "transactions": len(current_rows),
        "previous_transactions": len(previous_rows),
    }

    insights: list[dict[str, Any]] = []
    if not baseline_complete:
        insights.append({
            "tone": "neutral",
            "title": "The comparison is incomplete",
            "body": f"{', '.join(missing_baseline[:3])}{' and more' if len(missing_baseline) > 3 else ''} has no observed ledger history. Moneta will not estimate the missing period.",
        })
    else:
        direction = "rose" if current_base > previous_base else "fell" if current_base < previous_base else "held steady"
        change = pct_change(current_base, previous_base, True) or 0
        insights.append({
            "tone": "attention" if change > 10 else "positive" if change < 0 else "neutral",
            "title": f"Spending {direction} {abs(change):.1f}%",
            "body": f"The selected period moved {_money_text((current_value - previous_value), currency)} versus {period_label(previous_months)}.",
        })
        positive = [node for node in tree if node["delta"] > 0]
        if positive:
            lead = max(positive, key=lambda node: node["delta"])
            total_increase = sum(node["delta"] for node in positive)
            contribution = lead["delta"] / total_increase * 100 if total_increase else 0
            lead_merchant = max(lead["children"], key=lambda child: child["delta"], default=None)
            merchant_children = lead_merchant.get("children", []) if lead_merchant else []
            merchant_leaf = max(merchant_children, key=lambda child: child["delta"], default=None)
            merchant_text = f" {merchant_leaf['name']} is the largest merchant-level contributor." if merchant_leaf else ""
            insights.append({
                "tone": "attention",
                "title": f"{lead['name']} explains {contribution:.0f}% of increases",
                "body": f"It added {_money_text(lead['delta'], currency)} across {lead['transactions']} transactions.{merchant_text}",
            })
    merchant_totals: dict[str, float] = defaultdict(float)
    for item in current_rows:
        merchant_totals[str(item.get("merchant_clean") or "Unspecified")] += float(item["amount"])
    if merchant_totals and current_base:
        top_merchant, top_amount = max(merchant_totals.items(), key=lambda pair: pair[1])
        insights.append({
            "tone": "neutral",
            "title": f"{top_merchant} is the largest merchant",
            "body": f"It represents {top_amount / current_base * 100:.1f}% of selected spending across the current filter scope.",
        })

    scope_label = " / ".join([*sorted(category_set), *sorted(subcategory_set), *sorted(merchant_set)]) or "All spending"
    converted_transactions = []
    for item in sorted(current_rows, key=lambda row: (str(row.get("date")), str(row.get("txn_id"))), reverse=True)[:500]:
        converted_transactions.append({**item, "amount": round(float(item["amount"]) * factor, 2)})
    return {
        "meta": {
            **base_meta,
            "selected_month": current,
            "selected_months": current_months,
            "period_label": period_label(current_months),
            "previous_period_label": period_label(previous_months),
            "comparison_label": "Same period last year" if comparison_mode == "year" else "Previous period",
            "baseline_complete": baseline_complete,
            "missing_baseline_months": missing_baseline,
            "scope_label": scope_label,
        },
        "kpis": {
            "period": {"value": round(current_value, 2), "previous": round(previous_value, 2),
                       "change_pct": pct_change(current_base, previous_base, baseline_complete)},
            "monthly_average": {"value": round(current_value / window, 2),
                                "previous": round(previous_value / window, 2),
                                "change_pct": pct_change(current_base, previous_base, baseline_complete)},
            "year": {"value": round(current_value, 2), "previous": round(yearly_base * factor, 2),
                     "change_pct": pct_change(current_base, yearly_base, yearly_complete)},
            "transactions": len(current_rows),
            "daily_average": round(current_value / day_count, 2) if day_count else 0,
        },
        "trend": trend,
        "driver_summary": summary,
        "driver_rows": tree,
        "insights": insights[:3],
        "transactions": converted_transactions,
    }
