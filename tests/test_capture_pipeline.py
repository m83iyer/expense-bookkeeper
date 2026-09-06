import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import capture_pipeline
from capture_pipeline import process_raw_event, transaction_payload_from_raw


def test_unknown_merchant_becomes_review_row_not_drop():
    raw = "AED 155.40 spent on ExampleCard at XYZ123 UNKNOWN on 19/04/2026"
    txn = transaction_payload_from_raw(raw, {}, source="test")
    assert txn["status"] == "Review"
    assert txn["category"] == "Misc"
    assert txn["subcategory"] == "Other"
    assert "Unknown merchant" in txn["review_reason"]


def test_known_keyword_stays_confirmed():
    raw = "AED 87.00 spent on ExampleCard at STARBUCKS MAIN STREET on 19/04/2026"
    txn = transaction_payload_from_raw(raw, {}, source="test")
    assert txn["status"] == "Confirmed"
    assert txn["category"] == "Dining"


def test_hermes_confirmation_runs_after_successful_append(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_HERMES_TARGET", "whatsapp")
    monkeypatch.setattr(capture_pipeline, "append_rows", lambda config, rows, dry_run=False: 1)
    observed = {}

    def fake_send(event, **kwargs):
        observed.update({"event": event, **kwargs})
        return {"status": "sent"}

    monkeypatch.setattr(capture_pipeline, "send_confirmation", fake_send)
    config = {
        "armed": True,
        "confirmation": {"adapter": "whatsapp_hermes"},
        "hermes": {"target_env": "TEST_HERMES_TARGET", "state_dir": str(tmp_path),
                   "include_merchant": False},
    }
    result = process_raw_event(
        "AED 87.00 spent on ExampleCard at STARBUCKS MAIN STREET on 19/04/2026",
        config,
        source="test",
    )
    assert result["confirmation"]["status"] == "sent"
    assert observed["target"] == "whatsapp"
    assert observed["include_merchant"] is False


def test_hermes_failure_does_not_fail_committed_capture(monkeypatch):
    monkeypatch.setenv("TEST_HERMES_TARGET", "whatsapp")
    monkeypatch.setattr(capture_pipeline, "append_rows", lambda config, rows, dry_run=False: 1)
    monkeypatch.setattr(capture_pipeline, "send_confirmation", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    config = {"armed": True, "confirmation": {"adapter": "whatsapp_hermes"},
              "hermes": {"target_env": "TEST_HERMES_TARGET"}}
    result = process_raw_event(
        "AED 87.00 spent on ExampleCard at STARBUCKS MAIN STREET on 19/04/2026", config
    )
    assert result["appended"] == 1
    assert result["confirmation"]["status"] == "deferred"


def test_capture_loads_merchant_master_from_google_sheet(monkeypatch):
    class Worksheet:
        def __init__(self, rows):
            self.rows = rows

        def get_all_values(self):
            return self.rows

    class Sheet:
        def worksheet(self, name):
            if name == "MERCHANT_MASTER":
                return Worksheet([
                    ["banner"],
                    ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
                    ["Corner Cafe", "Corner Cafe", "Dining", "Cafe"],
                ])
            assert name == "CATEGORIES"
            return Worksheet([
                ["banner"],
                ["Category", "Subcategory", "Active"],
                ["Dining", "Cafe", "TRUE"],
                ["Misc", "Other", "TRUE"],
            ])

    monkeypatch.setattr(capture_pipeline, "open_spreadsheet", lambda config: Sheet())
    config = {
        "sheet": {
            "id": "sheet-id",
            "service_account_path": "/private/config.json",
            "merchant_tab": "MERCHANT_MASTER",
        }
    }
    txn = transaction_payload_from_raw(
        "AED 42.00 spent on ExampleCard at CORNER CAFE DOWNTOWN on 19/04/2026",
        config,
        source="test",
    )
    assert txn["status"] == "Confirmed"
    assert txn["category"] == "Dining"
    assert txn["subcategory"] == "Cafe"


def test_capture_refuses_master_mapping_outside_active_taxonomy(monkeypatch):
    class Worksheet:
        def __init__(self, rows):
            self.rows = rows

        def get_all_values(self):
            return self.rows

    class Sheet:
        def worksheet(self, name):
            if name == "MERCHANT_MASTER":
                return Worksheet([
                    ["banner"],
                    ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
                    ["Corner Cafe", "Corner Cafe", "Dining", "Typo"],
                ])
            return Worksheet([
                ["banner"],
                ["Category", "Subcategory", "Active"],
                ["Dining", "Cafe", "TRUE"],
            ])

    monkeypatch.setattr(capture_pipeline, "open_spreadsheet", lambda config: Sheet())
    config = {"sheet": {"id": "sheet-id", "service_account_path": "/private/config.json"}}
    try:
        transaction_payload_from_raw(
            "AED 42.00 spent on ExampleCard at CORNER CAFE on 19/04/2026",
            config,
            source="test",
        )
    except RuntimeError as exc:
        assert "not present in active CATEGORIES" in str(exc)
    else:
        raise AssertionError("invalid master taxonomy must fail closed")


def test_keyword_cue_outside_installed_taxonomy_becomes_review(monkeypatch):
    class Worksheet:
        def __init__(self, rows):
            self.rows = rows

        def get_all_values(self):
            return self.rows

    class Sheet:
        def worksheet(self, name):
            if name == "MERCHANT_MASTER":
                return Worksheet([
                    ["banner"],
                    ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
                ])
            return Worksheet([
                ["banner"],
                ["Category", "Subcategory", "Active"],
                ["Groceries", "Supermarket", "TRUE"],
                ["Misc", "Other", "TRUE"],
            ])

    monkeypatch.setattr(capture_pipeline, "open_spreadsheet", lambda config: Sheet())
    txn = transaction_payload_from_raw(
        "AED 42.00 spent on ExampleCard at STARBUCKS MAIN STREET on 19/04/2026",
        {"sheet": {"id": "sheet-id", "service_account_path": "/private/config.json"}},
        source="test",
    )
    assert txn["status"] == "Review"
    assert txn["category"] == "Misc"
    assert txn["subcategory"] == "Other"
    assert "not active in CATEGORIES" in txn["review_reason"]


def test_review_capture_refuses_missing_fallback_pair(monkeypatch):
    class Worksheet:
        def __init__(self, rows):
            self.rows = rows

        def get_all_values(self):
            return self.rows

    class Sheet:
        def worksheet(self, name):
            if name == "MERCHANT_MASTER":
                return Worksheet([
                    ["banner"],
                    ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
                ])
            return Worksheet([
                ["banner"],
                ["Category", "Subcategory", "Active"],
                ["Groceries", "Supermarket", "TRUE"],
            ])

    monkeypatch.setattr(capture_pipeline, "open_spreadsheet", lambda config: Sheet())
    with pytest.raises(RuntimeError, match="Misc / Other"):
        transaction_payload_from_raw(
            "AED 42.00 spent on ExampleCard at UNKNOWN MERCHANT on 19/04/2026",
            {"sheet": {"id": "sheet-id", "service_account_path": "/private/config.json"}},
            source="test",
        )


def test_unarmed_capture_is_forced_to_dry_run_and_sends_no_confirmation(monkeypatch):
    observed = {}

    def fake_append(config, rows, dry_run=False):
        observed["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(capture_pipeline, "append_rows", fake_append)
    monkeypatch.setattr(
        capture_pipeline,
        "send_confirmation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not send")),
    )
    result = process_raw_event(
        "AED 87.00 spent on ExampleCard at STARBUCKS MAIN STREET on 19/04/2026",
        {"armed": False, "confirmation": {"adapter": "whatsapp_hermes"}},
        source="test",
    )
    assert observed["dry_run"] is True
    assert result["dry_run"] is True
    assert result["appended"] == 0


def test_user_selected_cash_category_is_preserved_without_learning_a_merchant_rule(monkeypatch):
    captured = {}

    def fake_append(config, rows, dry_run=False):
        captured["row"] = rows[0]
        return 1

    monkeypatch.setattr(capture_pipeline, "append_rows", fake_append)
    result = process_raw_event(
        "AED 42.00 at NEIGHBOURHOOD STALL on 20-07-2026",
        {"armed": True},
        source="dashboard_cash",
        category_override="Groceries",
        subcategory_override="Market",
        notes="Fresh produce",
    )
    assert result["transaction"]["category"] == "Groceries"
    assert result["transaction"]["subcategory"] == "Market"
    assert result["transaction"]["notes"] == "Fresh produce"
    assert result["transaction"]["learning_scope"] == "transaction_only"
    assert result["transaction"]["status"] == "Confirmed"
    assert captured["row"][7:9] == ["Groceries", "Market"]


def test_capture_reuses_confirmed_history_from_local_dashboard_mirror(tmp_path):
    database = tmp_path / "dashboard.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE transactions (
        date TEXT, amount REAL, merchant_clean TEXT, category TEXT,
        subcategory TEXT, card_used TEXT, source TEXT, status TEXT
        )"""
    )
    connection.executemany(
        "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)",
        [
            ("2026-05-01", 25, "Acme Futura", "Travel", "Rail", "Visa", "sms", "Confirmed"),
            ("2026-06-01", 31, "Acme Futura", "Travel", "Rail", "Visa", "sms", "Confirmed"),
        ],
    )
    connection.commit()
    connection.close()

    txn = transaction_payload_from_raw(
        "AED 25.00 spent on Visa at ACME FUTURA on 01/07/2026",
        {"dashboard": {"database_path": str(database)}},
        source="sms",
    )
    assert txn["status"] == "Confirmed"
    assert (txn["category"], txn["subcategory"]) == ("Travel", "Rail")


def test_opted_in_web_research_adds_ranked_review_choice(monkeypatch):
    observed = []

    def fake_enrich(merchant, config):
        observed.append(merchant)
        return {"evidence": [{"title": f"{merchant} powered by Starbucks", "snippet": "Cafe"}]}

    monkeypatch.setattr(capture_pipeline, "enrich_merchant", fake_enrich)
    txn = transaction_payload_from_raw(
        "AED 18.00 spent on Visa at HIDDEN CAFE on 01/07/2026",
        {"categorization": {"web_enrichment": "always", "web_enrichment_provider": "test"}},
        source="sms",
    )
    assert observed == ["HIDDEN CAFE"]
    assert txn["status"] == "Review"
    assert txn["research_attempted"] is True
    assert txn["review_options"][0]["category"] == "Dining"
