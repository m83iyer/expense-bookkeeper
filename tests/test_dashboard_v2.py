from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dashboard.demo import DEMO_RATES, demo_commitments, demo_transactions
from dashboard.fx import write_snapshot
from dashboard.server import Dashboard
from dashboard.sync import build_database


def _dashboard(tmp_path: Path) -> Dashboard:
    database = tmp_path / "dashboard.sqlite3"
    fx_path = tmp_path / "fx.json"
    config_path = tmp_path / "config.yaml"
    build_database(database, demo_transactions(), demo_commitments(), currency="USD")
    write_snapshot(fx_path, {
        "base": "USD", "as_of": "synthetic", "rates": DEMO_RATES,
        "source": "Synthetic demonstration rates", "source_url": None, "mode": "synthetic",
    })
    config_path.write_text(yaml.safe_dump({
        "locale": {"default_currency": "USD"},
        "dashboard": {"fx_rates_path": str(fx_path), "demo_mode": True},
    }))
    return Dashboard(config_path, database)


def test_three_month_period_has_complete_previous_period_and_driver_tree(tmp_path: Path):
    data = _dashboard(tmp_path).analytics("Aug-2026", 3, "", "", "", "previous", "USD")
    assert data["meta"]["period_label"] == "Jun 2026 to Aug 2026"
    assert data["meta"]["previous_period_label"] == "Mar 2026 to May 2026"
    assert data["meta"]["baseline_complete"] is True
    assert data["kpis"]["period"]["value"] > data["kpis"]["period"]["previous"]
    assert data["driver_rows"]
    assert all(node["children"] for node in data["driver_rows"])
    assert round(sum(node["current"] for node in data["driver_rows"]), 2) == data["driver_summary"]["current"]
    travel = next(node for node in data["driver_rows"] if node["name"] == "Travel")
    assert {child["name"] for child in travel["children"]} >= {"Accommodation", "Local transport"}
    assert any(leaf["name"] == "Airbnb" for child in travel["children"] for leaf in child["children"])


def test_currency_toggle_converts_every_monetary_surface(tmp_path: Path):
    dashboard = _dashboard(tmp_path)
    usd = dashboard.analytics("Aug-2026", 3, "", "", "", "previous", "USD")
    inr = dashboard.analytics("Aug-2026", 3, "", "", "", "previous", "INR")
    assert inr["meta"]["available_currencies"] == ["USD", "INR", "GBP", "EUR", "AED"]
    assert inr["meta"]["currency"] == "INR"
    assert inr["kpis"]["period"]["value"] == round(usd["kpis"]["period"]["value"] * DEMO_RATES["INR"], 2)
    assert inr["driver_rows"][0]["current"] == pytest.approx(
        usd["driver_rows"][0]["current"] * DEMO_RATES["INR"], abs=0.02
    )
    assert inr["transactions"][0]["amount"] == round(usd["transactions"][0]["amount"] * DEMO_RATES["INR"], 2)
    commitments = dashboard.commitments("EUR")
    assert commitments["currency"] == "EUR"
    assert commitments["annual_total"] == round(sum(item["monthly_amount"] for item in demo_commitments()) * 12 * DEMO_RATES["EUR"], 2)


def test_merchant_filter_and_evidence_share_one_scope(tmp_path: Path):
    data = _dashboard(tmp_path).analytics("Aug-2026", 3, "Travel", "Accommodation", "Airbnb", "previous", "GBP")
    assert data["meta"]["scope_label"] == "Travel / Accommodation / Airbnb"
    assert data["transactions"]
    assert {item["merchant_clean"] for item in data["transactions"]} == {"Airbnb"}
    assert [node["name"] for node in data["driver_rows"]] == ["Travel"]


def test_comparison_fails_closed_when_history_is_unobserved(tmp_path: Path):
    records = [item for item in demo_transactions() if item["month_year"] in {"Jul-2026", "Aug-2026"}]
    database = tmp_path / "short.sqlite3"
    config_path = tmp_path / "config.yaml"
    build_database(database, records, [], currency="USD")
    config_path.write_text(yaml.safe_dump({"locale": {"default_currency": "USD"}, "dashboard": {}}))
    data = Dashboard(config_path, database).analytics("Aug-2026", 2, "", "", "", "previous", "USD")
    assert data["meta"]["baseline_complete"] is False
    assert data["meta"]["missing_baseline_months"] == ["May-2026", "Jun-2026"]
    assert data["kpis"]["period"]["change_pct"] is None
    assert data["driver_rows"][0]["pct"] is None
    assert data["insights"][0]["title"] == "The comparison is incomplete"


def test_demo_has_only_synthetic_markers_and_global_merchants():
    records = demo_transactions()
    assert len(records) > 300
    merchants = {item["merchant_clean"] for item in records}
    assert {"Amazon", "Apple", "Airbnb", "Uber", "Carrefour", "Netflix", "Spotify"} <= merchants
    encoded = json.dumps(records)
    assert "/Users/" not in encoded
    assert "@" not in encoded
    assert all(item["notes"].startswith("Synthetic") for item in records)


def test_demo_is_labeled_and_does_not_guess_non_monthly_due_dates(tmp_path: Path):
    dashboard = _dashboard(tmp_path)
    data = dashboard.analytics("Aug-2026", 3, "", "", "", "previous", "USD")
    commitments = dashboard.commitments("USD")
    assert data["meta"]["demo_mode"] is True
    assert commitments["demo_mode"] is True
    assert "Strava" in {item["name"] for item in commitments["commitments"]}
    assert "Strava" not in {item["name"] for item in commitments["upcoming"]}
