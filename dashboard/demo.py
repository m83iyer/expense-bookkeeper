#!/usr/bin/env python3
"""Build a deterministic, privacy-safe Moneta demonstration ledger."""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from dashboard.fx import write_snapshot
from dashboard.intelligence import shift_month
from dashboard.sync import build_database

DEMO_END_MONTH = "Aug-2026"
DEMO_RATES = {"USD": 1.0, "INR": 95.46, "GBP": 0.7364, "EUR": 0.85876, "AED": 3.6725}

MERCHANTS = [
    ("Carrefour", "Groceries & Household", "Supermarket", 84, 3),
    ("Whole Foods Market", "Groceries & Household", "Supermarket", 72, 2),
    ("Starbucks", "Dining & Cafes", "Coffee", 12, 3),
    ("Uber", "Transport & Mobility", "Ride hailing", 26, 4),
    ("Shell", "Transport & Mobility", "Fuel", 58, 2),
    ("Amazon", "Shopping", "Online retail", 95, 2),
    ("IKEA", "Home", "Furnishings", 130, 1),
    ("Uniqlo", "Shopping", "Apparel", 68, 1),
    ("Apple", "Shopping", "Electronics", 42, 1),
    ("Netflix", "Entertainment", "Streaming", 18, 1),
    ("Spotify", "Entertainment", "Streaming", 12, 1),
    ("Microsoft", "Software & AI", "Productivity", 15, 1),
    ("GitHub", "Software & AI", "Developer tools", 10, 1),
    ("Google", "Software & AI", "Cloud storage", 6, 1),
]


def _iso_day(month: str, day: int) -> str:
    year, month_number = datetime.strptime(month, "%b-%Y").year, datetime.strptime(month, "%b-%Y").month
    return date(year, month_number, min(day, 28)).isoformat()


def demo_transactions() -> list[dict[str, Any]]:
    rng = random.Random(20260831)
    months = [shift_month(DEMO_END_MONTH, offset) for offset in range(-17, 1)]
    rows: list[dict[str, Any]] = []
    counter = 0
    for month_index, month in enumerate(months):
        for merchant, category, subcategory, average, frequency in MERCHANTS:
            for occurrence in range(frequency):
                counter += 1
                seasonal = 1 + 0.035 * (month_index % 4)
                amount = max(2, average * seasonal * rng.uniform(0.72, 1.28))
                rows.append({
                    "txn_id": f"DEMO-{counter:04d}",
                    "date": _iso_day(month, 2 + ((counter * 3 + occurrence) % 25)),
                    "month_year": month,
                    "amount": round(amount, 2),
                    "currency": "USD",
                    "txn_type": "Expense",
                    "category": category,
                    "subcategory": subcategory,
                    "merchant_clean": merchant,
                    "card_used": "Everyday card",
                    "source": "Card alert",
                    "person": "Demo household",
                    "notes": "Synthetic demonstration transaction",
                    "status": "Confirmed",
                })
        if month in {"Jul-2026", "Aug-2026"}:
            travel = [
                ("Airbnb", "Accommodation", 1180 if month == "Jul-2026" else 640, 12),
                ("Booking.com", "Accommodation", 420 if month == "Jul-2026" else 310, 16),
                ("Uber", "Local transport", 180 if month == "Jul-2026" else 145, 21),
            ]
            for merchant, subcategory, amount, day in travel:
                counter += 1
                rows.append({
                    "txn_id": f"DEMO-{counter:04d}", "date": _iso_day(month, day), "month_year": month,
                    "amount": float(amount), "currency": "USD", "txn_type": "Expense", "category": "Travel",
                    "subcategory": subcategory, "merchant_clean": merchant, "card_used": "Travel card",
                    "source": "Card alert", "person": "Demo household",
                    "notes": "Synthetic summer travel", "status": "Confirmed",
                })
        if month == "Aug-2026":
            counter += 1
            rows.append({
                "txn_id": f"DEMO-{counter:04d}", "date": _iso_day(month, 18), "month_year": month,
                "amount": 899.0, "currency": "USD", "txn_type": "Expense", "category": "Shopping",
                "subcategory": "Electronics", "merchant_clean": "Apple", "card_used": "Everyday card",
                "source": "Card alert", "person": "Demo household", "notes": "Synthetic device purchase",
                "status": "Confirmed",
            })
    return rows


def demo_commitments() -> list[dict[str, Any]]:
    return [
        {"name": "Netflix", "category": "Entertainment", "subcategory": "Streaming", "currency": "USD", "monthly_amount": 17.99, "day_of_month": 4, "cadence": "monthly", "payment_amount": 17.99},
        {"name": "Amazon Prime", "category": "Shopping", "subcategory": "Memberships", "currency": "USD", "monthly_amount": 14.99, "day_of_month": 6, "cadence": "monthly", "payment_amount": 14.99},
        {"name": "Spotify", "category": "Entertainment", "subcategory": "Streaming", "currency": "USD", "monthly_amount": 11.99, "day_of_month": 8, "cadence": "monthly", "payment_amount": 11.99},
        {"name": "Microsoft 365", "category": "Software & AI", "subcategory": "Productivity", "currency": "USD", "monthly_amount": 9.99, "day_of_month": 11, "cadence": "monthly", "payment_amount": 9.99},
        {"name": "The Economist", "category": "News & Learning", "subcategory": "Publications", "currency": "USD", "monthly_amount": 19.90, "day_of_month": 13, "cadence": "monthly", "payment_amount": 19.90},
        {"name": "Adobe", "category": "Software & AI", "subcategory": "Creative tools", "currency": "USD", "monthly_amount": 22.99, "day_of_month": 14, "cadence": "monthly", "payment_amount": 22.99},
        {"name": "Uber One", "category": "Transport & Mobility", "subcategory": "Memberships", "currency": "USD", "monthly_amount": 9.99, "day_of_month": 17, "cadence": "monthly", "payment_amount": 9.99},
        {"name": "Google One", "category": "Software & AI", "subcategory": "Cloud storage", "currency": "USD", "monthly_amount": 9.99, "day_of_month": 19, "cadence": "monthly", "payment_amount": 9.99},
        {"name": "Strava", "category": "Health & Fitness", "subcategory": "Fitness apps", "currency": "USD", "monthly_amount": 6.67, "day_of_month": 23, "cadence": "annual", "payment_amount": 79.99},
        {"name": "Dropbox", "category": "Software & AI", "subcategory": "Cloud storage", "currency": "USD", "monthly_amount": 11.99, "day_of_month": 25, "cadence": "monthly", "payment_amount": 11.99},
    ]


def build_demo(output: Path) -> dict[str, str]:
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    database = output / "moneta-demo.sqlite3"
    fx_path = output / "fx-rates.json"
    config_path = output / "config.demo.yaml"
    build_database(database, demo_transactions(), demo_commitments(), currency="USD")
    write_snapshot(fx_path, {
        "schema_version": 1,
        "base": "USD",
        "as_of": "synthetic",
        "rates": DEMO_RATES,
        "source": "Synthetic demonstration rates",
        "source_url": None,
        "retrieved_at": "2026-08-31T00:00:00+00:00",
        "mode": "synthetic",
    })
    config_path.write_text(yaml.safe_dump({
        "locale": {"default_currency": "USD", "date_formats": ["%Y-%m-%d"]},
        "dashboard": {
            "database_path": str(database),
            "fx_rates_path": str(fx_path),
            "allow_cash_entry": False,
            "allow_lan_writes": False,
            "demo_mode": True,
        },
    }, sort_keys=False), encoding="utf-8")
    return {"config": str(config_path), "database": str(database), "fx": str(fx_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"status": "ok", **build_demo(args.output)}, indent=2))


if __name__ == "__main__":
    main()
