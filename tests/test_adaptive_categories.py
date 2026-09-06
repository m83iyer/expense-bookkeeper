import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from adaptive_categories import AdaptiveCategoryStore


def store(tmp_path):
    return AdaptiveCategoryStore(tmp_path / "adaptive.json")


def test_confirmed_correction_learns_and_resolves_longest_match(tmp_path):
    subject = store(tmp_path)
    result = subject.learn_confirmed("Coffee", "Dining", "Cafe")
    subject.learn_confirmed("Coffee House", "Dining", "Restaurant")
    assert result["action"] == "learned"
    assert subject.resolve("COFFEE HOUSE DOWNTOWN")["subcategory"] == "Restaurant"


def test_generic_merchant_is_never_learned(tmp_path):
    with pytest.raises(ValueError, match="too vague"):
        store(tmp_path).learn_confirmed("merchant", "Shopping")


def test_conflict_creates_proposal_and_requires_approval(tmp_path):
    subject = store(tmp_path)
    subject.learn_confirmed("Corner Shop", "Shopping")
    result = subject.learn_confirmed("Corner Shop", "Groceries", "Convenience")
    assert result["action"] == "proposal_created"
    assert subject.resolve("Corner Shop")["category"] == "Shopping"
    subject.approve(result["proposal"]["proposal_id"])
    assert subject.resolve("Corner Shop")["category"] == "Groceries"


def test_repeated_evidence_is_opt_in_and_deduplicated(tmp_path):
    subject = store(tmp_path)
    first = subject.observe("New Cafe", "Dining", "Cafe", confidence=0.99, evidence_id="e1")
    duplicate = subject.observe("New Cafe", "Dining", "Cafe", confidence=0.99, evidence_id="e1")
    assert first["action"] == "observed_opt_in_required"
    assert duplicate["action"] == "noop_duplicate_evidence"
    assert subject.resolve("New Cafe") is None


def test_opted_in_repeated_evidence_promotes_only_at_threshold(tmp_path):
    subject = store(tmp_path)
    subject.configure(auto_promote_repeated=True, minimum_observations=3, minimum_confidence=0.9)
    assert subject.observe("New Cafe", "Dining", "Cafe", confidence=0.95, evidence_id="1")["action"] == "observed_below_threshold"
    assert subject.observe("New Cafe", "Dining", "Cafe", confidence=0.95, evidence_id="2")["action"] == "observed_below_threshold"
    assert subject.observe("New Cafe", "Dining", "Cafe", confidence=0.95, evidence_id="3")["action"] == "learned"


def test_taxonomy_change_is_only_an_approved_event(tmp_path):
    subject = store(tmp_path)
    proposal = subject.propose_taxonomy_change("split", {"from": "Dining", "into": ["Dining", "Coffee"]}, impacted_transactions=14)
    assert subject.state["taxonomy_events"] == []
    subject.approve(proposal["proposal_id"])
    assert subject.state["taxonomy_events"][0]["kind"] == "taxonomy_split"


def test_rule_add_can_be_rolled_back(tmp_path):
    subject = store(tmp_path)
    subject.learn_confirmed("Bakery", "Dining")
    event_id = subject.state["history"][-1]["event_id"]
    assert subject.rollback(event_id)["action"] == "rolled_back"
    assert subject.resolve("Bakery") is None
