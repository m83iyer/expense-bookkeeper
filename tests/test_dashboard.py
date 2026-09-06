from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from dashboard import server as dashboard_server
from dashboard.server import Dashboard
from dashboard.sync import build_database, normalize_expenses, normalize_recurring


def config() -> dict:
    return {"locale": {"default_currency": "AED", "date_formats": ["%d/%m/%Y"]}}


def transaction(txn_id: str, day: str, amount: float, category: str = "Dining") -> dict:
    return {
        "txn_id": txn_id, "date": day,
        "month_year": datetime.fromisoformat(day).strftime("%b-%Y"),
        "amount": amount, "currency": "AED", "txn_type": "Expense",
        "category": category, "subcategory": "Restaurants",
        "merchant_clean": f"Merchant {txn_id}", "card_used": "Card",
        "source": "test", "person": "Household", "notes": "", "status": "Confirmed",
    }


def test_expense_rows_are_header_driven_and_dates_are_normalized():
    rows = [
        ["report title"],
        ["Txn_ID", "Date", "Amount", "Currency", "Txn_Type", "Category",
         "Subcategory", "Merchant_Clean", "Status"],
        ["abc", "15/07/2026", "1,234.50", "AED", "Expense", "Travel",
         "Flights", "Example Air", "Confirmed"],
    ]
    result = normalize_expenses(rows, config())
    assert result[0]["date"] == "2026-07-15"
    assert result[0]["amount"] == 1234.50
    assert result[0]["month_year"] == "Jul-2026"


def test_recurring_items_are_normalized_to_monthly():
    rows = [
        ["Description", "Amount", "Currency", "Category", "Subcategory",
         "Cadence", "Day_of_Month", "Active"],
        ["Home", "12000", "AED", "Housing", "Rent", "Yearly", "15", "true"],
        ["Service", "300", "AED", "Household", "Services", "Quarterly", "1", "yes"],
    ]
    result = normalize_recurring(rows, "AED")
    assert [item["monthly_amount"] for item in result] == [1000.0, 100.0]
    assert [item["payment_amount"] for item in result] == [12000.0, 300.0]
    assert [item["cadence"] for item in result] == ["yearly", "quarterly"]


def test_analytics_produces_period_yoy_and_drilldown(tmp_path: Path):
    db = tmp_path / "dashboard.sqlite3"
    records = [
        transaction("a", "2025-07-10", 80),
        transaction("b", "2026-06-10", 100),
        transaction("c", "2026-07-10", 150),
        transaction("d", "2026-07-11", 50, "Travel"),
    ]
    build_database(db, records, [], currency="AED")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"locale": {"default_currency": "AED"}, "dashboard": {}}))
    data = Dashboard(config_path, db).analytics("Jul-2026", 1, "", "")
    assert data["kpis"]["period"]["value"] == 200
    assert data["kpis"]["period"]["change_pct"] == 100
    assert data["kpis"]["year"]["change_pct"] == 150
    assert {item["name"] for item in data["driver_rows"]} == {"Dining", "Travel"}
    dining = Dashboard(config_path, db).analytics("Jul-2026", 1, "Dining", "")
    assert dining["meta"]["scope_label"] == "Dining"
    assert dining["kpis"]["period"]["value"] == 150
    combined = Dashboard(config_path, db).analytics("Jul-2026", 1, "Dining|Travel", "")
    assert combined["kpis"]["period"]["value"] == 200
    assert combined["meta"]["category"] == "Dining|Travel"


def test_dashboard_source_contains_no_personalized_brand_or_absolute_home_path():
    root = Path(__file__).resolve().parents[1] / "dashboard"
    source = "\n".join(
        path.read_text() for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
    )
    assert "Manoj" + " Finance" not in source
    assert "/" + "Users/" not in source


def test_cash_entry_uses_a_parseable_alert_and_preserves_selected_taxonomy(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"locale": {"default_currency": "AED"}, "dashboard": {}}))
    captured = {}

    def fake_process(raw, supplied_config, **kwargs):
        captured.update({"raw": raw, "config": supplied_config, **kwargs})
        return {"appended": True, "transaction": {"status": "Confirmed"}}

    monkeypatch.setattr(dashboard_server, "process_raw_event", fake_process)
    result = Dashboard(config_path, tmp_path / "unused.sqlite3").log_cash({
        "amount": "42",
        "date": "2026-07-20",
        "merchant": "Neighbourhood Stall",
        "category": "Dining & Cafes",
        "subcategory": "Takeaway",
        "notes": "cash lunch",
    })

    assert captured["raw"] == "AED 42.00 at Neighbourhood Stall on 20-07-2026"
    assert captured["source"] == "dashboard_cash"
    assert captured["category_override"] == "Dining & Cafes"
    assert captured["subcategory_override"] == "Takeaway"
    assert captured["notes"] == "cash lunch"
    assert result["status"] == "logged"


def test_dashboard_uses_power_bi_style_multi_choice_slicers():
    static = Path(__file__).resolve().parents[1] / "dashboard" / "static"
    html = (static / "index.html").read_text()
    script = (static / "app.js").read_text()
    for slicer in ("categoryFilter", "subcategoryFilter", "merchantFilter"):
        assert f'id="{slicer}" class="multi-slicer"' in html
    assert "Select all" in script
    assert "Clear all" in script
    assert 'chosen.join("|")' in script
