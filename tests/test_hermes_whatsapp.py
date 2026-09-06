import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "adapters"))
from hermes_whatsapp import format_confirmation, parse_inbound_command, queue_inbound_command, send_confirmation


EVENT = {"event_id": "txn-1", "amount": "12.50", "currency": "USD", "merchant": "Cafe", "category": "Dining"}


def test_send_is_disabled_without_user_target(tmp_path):
    assert send_confirmation(EVENT, target="", state_dir=tmp_path)["status"] == "disabled"


def test_dry_run_does_not_write_delivery_state(tmp_path):
    result = send_confirmation(EVENT, target="whatsapp", state_dir=tmp_path, dry_run=True)
    assert result["status"] == "dry_run"
    assert not (tmp_path / "delivery_state.json").exists()


def test_successful_send_uses_argument_list_and_is_idempotent(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='{"ok": true}', stderr="")

    assert send_confirmation(EVENT, target="whatsapp:owner", state_dir=tmp_path, runner=runner)["status"] == "sent"
    assert calls[0][0] == ["hermes", "send", "--to", "whatsapp:owner", "--file", "-", "--json"]
    assert send_confirmation(EVENT, target="whatsapp:owner", state_dir=tmp_path, runner=runner)["status"] == "duplicate"
    assert len(calls) == 1


def test_delivery_failure_is_deferred_not_raised(tmp_path):
    def runner(command, **kwargs):
        raise FileNotFoundError("hermes")

    result = send_confirmation(EVENT, target="whatsapp", state_dir=tmp_path, runner=runner)
    assert result["status"] == "deferred"


def test_inbound_command_is_narrow_and_bulk_is_flagged(tmp_path):
    assert parse_inbound_command("hello there", txn_id="txn-1") is None
    option = parse_inbound_command("2", txn_id="txn-1")
    assert option["kind"] == "review_option_selection"
    assert option["option"] == 2
    assert parse_inbound_command("2") is None
    last = parse_inbound_command("change to Groceries / Supermarket", txn_id="txn-1")
    assert last["kind"] == "transaction_correction"
    named = queue_inbound_command("change Corner Shop to Groceries", state_dir=tmp_path)
    assert named["status"] == "queued"
    assert named["command"]["requires_bulk_confirmation"] is True


def test_review_message_does_not_claim_the_expense_was_confirmed():
    message = format_confirmation({
        **EVENT,
        "status": "Review",
        "review_reason": "Unknown merchant",
        "category": "Misc",
        "subcategory": "Other",
    })
    assert message.startswith("Expense needs review:")
    assert "Expense logged:" not in message
    assert "Unknown merchant" in message


def test_review_message_presents_ranked_easy_reply_options():
    message = format_confirmation({
        **EVENT,
        "status": "Review",
        "review_reason": "New merchant",
        "review_options": [
            {"category": "Dining & Cafes", "subcategory": "Restaurants"},
            {"category": "Groceries & Household", "subcategory": "Supermarket"},
        ],
        "research_attempted": True,
    })
    assert "history and merchant research checked" in message
    assert "1. Dining & Cafes / Restaurants" in message
    assert "2. Groceries & Household / Supermarket" in message
    assert "Reply 1, 2 or 3" in message


def test_transaction_only_review_does_not_claim_future_learning():
    message = format_confirmation({
        **EVENT,
        "merchant": "PAYMENT",
        "status": "Review",
        "learning_scope": "transaction_only",
        "review_options": [
            {"category": "Housing & Home", "subcategory": "House Help"},
        ],
    })
    assert "applies only to this transaction" in message
    assert "will not teach a merchant rule" in message
