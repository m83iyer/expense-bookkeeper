from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.fx import SUPPORTED_CURRENCIES, currency_context, load_snapshot, refresh_snapshot, write_snapshot


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_refresh_writes_valid_five_currency_snapshot(tmp_path: Path):
    rows = [
        {"date": "2026-08-31", "base": "USD", "quote": "INR", "rate": 95.46},
        {"date": "2026-08-31", "base": "USD", "quote": "GBP", "rate": .7364},
        {"date": "2026-08-31", "base": "USD", "quote": "EUR", "rate": .85876},
        {"date": "2026-08-31", "base": "USD", "quote": "AED", "rate": 3.6725},
    ]
    output = tmp_path / "fx.json"
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        return _Response(rows)

    payload = refresh_snapshot({"locale": {"default_currency": "USD"}}, output, opener=opener)
    assert payload["as_of"] == "2026-08-31"
    assert tuple(payload["rates"]) == SUPPORTED_CURRENCIES
    assert "quotes=INR%2CGBP%2CEUR%2CAED" in seen["url"]
    assert load_snapshot({"dashboard": {"fx_rates_path": str(output)}}, "USD")["rates"]["AED"] == 3.6725


def test_currency_context_falls_back_to_base_when_no_snapshot(tmp_path: Path):
    config = {"dashboard": {"fx_rates_path": str(tmp_path / "missing.json")}}
    context = currency_context(config, "GBP", "USD")
    assert context["quote"] == "GBP"
    assert context["available"] == ["GBP"]


def test_invalid_snapshot_fails_closed(tmp_path: Path):
    path = tmp_path / "fx.json"
    write_snapshot(path, {"base": "USD", "rates": {"USD": 1, "INR": 95, "GBP": .7, "EUR": .85, "AED": 0}})
    with pytest.raises(ValueError, match="invalid USD/AED"):
        load_snapshot({"dashboard": {"fx_rates_path": str(path)}}, "USD")
