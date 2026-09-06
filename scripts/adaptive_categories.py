#!/usr/bin/env python3
"""Local, auditable merchant learning for expense-bookkeeper.

The tracker can learn a merchant mapping immediately from an explicit user
correction. It may also learn from repeated high-confidence observations when
the user opts in. Existing mappings are never silently overwritten and
taxonomy changes are proposals until explicitly approved.

State lives in the user's configured state directory. Nothing is transmitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from merchant_resolver import GENERIC_NOISE, normalise_merchant, phrase_matches_tokens, tokens_of


STATE_VERSION = 1
DEFAULT_STATE = Path.home() / ".expense-bookkeeper" / "state" / "adaptive_categories.json"
DEFAULT_AUDIT = Path.home() / ".expense-bookkeeper" / "state" / "adaptive_categories.audit.jsonl"
ALLOWED_TAXONOMY_CHANGES = {"rename", "split", "merge"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts + (_now(),))
    return f"{prefix}_{hashlib.sha256(material.encode()).hexdigest()[:12]}"


def _blank_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "settings": {
            "auto_promote_repeated": False,
            "minimum_observations": 3,
            "minimum_confidence": 0.90,
        },
        "rules": {},
        "observations": {},
        "proposals": {},
        "taxonomy_events": [],
        "history": [],
    }


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class AdaptiveCategoryStore:
    """Owns local adaptive-category state and its append-only audit trail."""

    def __init__(self, state_path: str | Path = DEFAULT_STATE, audit_path: str | Path | None = None):
        self.state_path = Path(state_path).expanduser()
        self.audit_path = Path(audit_path).expanduser() if audit_path else self.state_path.with_suffix(".audit.jsonl")
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return _blank_state()
        loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        if loaded.get("version") != STATE_VERSION:
            raise ValueError(f"Unsupported adaptive state version: {loaded.get('version')}")
        baseline = _blank_state()
        for key, value in baseline.items():
            loaded.setdefault(key, value)
        for key, value in baseline["settings"].items():
            loaded["settings"].setdefault(key, value)
        return loaded

    def _save(self) -> None:
        _atomic_json_write(self.state_path, self.state)

    def _audit(self, event: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"at": _now(), **event}
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        os.chmod(self.audit_path, 0o600)

    @staticmethod
    def _merchant_key(merchant: str) -> str:
        key = normalise_merchant(merchant)
        if not key or key in GENERIC_NOISE or len(key) < 3:
            raise ValueError("Merchant is too vague to learn safely")
        return key

    @staticmethod
    def _mapping(category: str, subcategory: str = "", merchant_clean: str = "") -> dict[str, str]:
        category = category.strip()
        if not category:
            raise ValueError("Category is required")
        return {
            "category": category,
            "subcategory": subcategory.strip(),
            "merchant_clean": merchant_clean.strip(),
        }

    def configure(self, *, auto_promote_repeated: bool | None = None,
                  minimum_observations: int | None = None,
                  minimum_confidence: float | None = None) -> dict[str, Any]:
        settings = self.state["settings"]
        before = settings.copy()
        if auto_promote_repeated is not None:
            settings["auto_promote_repeated"] = bool(auto_promote_repeated)
        if minimum_observations is not None:
            if minimum_observations < 2:
                raise ValueError("minimum_observations must be at least 2")
            settings["minimum_observations"] = int(minimum_observations)
        if minimum_confidence is not None:
            if not 0 <= minimum_confidence <= 1:
                raise ValueError("minimum_confidence must be between 0 and 1")
            settings["minimum_confidence"] = float(minimum_confidence)
        if settings != before:
            self._save()
            self._audit({"event": "settings_updated", "settings": settings})
        return settings.copy()

    def resolve(self, merchant: str) -> dict[str, Any] | None:
        input_tokens = tokens_of(merchant)
        matches = []
        for key, rule in self.state["rules"].items():
            if rule.get("active", True) and phrase_matches_tokens(key.split(), input_tokens):
                matches.append((len(key.split()), len(key), key, rule))
        if not matches:
            return None
        _, _, key, rule = max(matches)
        return {"merchant_key": key, **rule}

    def learn_confirmed(self, merchant: str, category: str, subcategory: str = "",
                        *, merchant_clean: str = "", source_txn_id: str = "") -> dict[str, Any]:
        """Learn from an explicit user correction; conflicts become proposals."""
        key = self._merchant_key(merchant)
        mapping = self._mapping(category, subcategory, merchant_clean or merchant)
        existing = self.state["rules"].get(key)
        if existing and all(existing.get(k, "") == mapping[k] for k in ("category", "subcategory")):
            return {"action": "noop_already_set", "merchant_key": key, "rule": existing}
        if existing:
            proposal = self._new_mapping_proposal(key, existing, mapping, "confirmed_correction_conflict")
            return {"action": "proposal_created", "proposal": proposal}

        rule = {
            **mapping,
            "source": "confirmed_correction",
            "source_txn_id": source_txn_id,
            "created_at": _now(),
            "active": True,
        }
        self.state["rules"][key] = rule
        history = {"event_id": _id("event", key), "event": "rule_added", "merchant_key": key,
                   "before": None, "after": rule, "at": _now(), "rolled_back": False}
        self.state["history"].append(history)
        self._save()
        self._audit({"event": "rule_added", "merchant_key": key, "mapping": mapping,
                     "source": "confirmed_correction", "source_txn_id": source_txn_id})
        return {"action": "learned", "merchant_key": key, "rule": rule}

    def observe(self, merchant: str, category: str, subcategory: str = "", *,
                confidence: float, evidence_id: str = "") -> dict[str, Any]:
        """Record a prediction and optionally promote repeated consistent evidence."""
        key = self._merchant_key(merchant)
        mapping = self._mapping(category, subcategory, merchant)
        settings = self.state["settings"]
        if confidence < settings["minimum_confidence"]:
            return {"action": "ignored_low_confidence", "merchant_key": key}

        signature = f"{mapping['category']}\x1f{mapping['subcategory']}"
        bucket = self.state["observations"].setdefault(key, {})
        evidence = bucket.setdefault(signature, {"count": 0, "mapping": mapping, "evidence_ids": []})
        if evidence_id and evidence_id in evidence["evidence_ids"]:
            return {"action": "noop_duplicate_evidence", "merchant_key": key}
        evidence["count"] += 1
        if evidence_id:
            evidence["evidence_ids"].append(evidence_id)
            evidence["evidence_ids"] = evidence["evidence_ids"][-20:]
        self._save()

        if not settings["auto_promote_repeated"]:
            return {"action": "observed_opt_in_required", "merchant_key": key, "count": evidence["count"]}
        if evidence["count"] < settings["minimum_observations"]:
            return {"action": "observed_below_threshold", "merchant_key": key, "count": evidence["count"]}

        existing = self.state["rules"].get(key)
        if existing:
            if all(existing.get(k, "") == mapping[k] for k in ("category", "subcategory")):
                return {"action": "noop_already_set", "merchant_key": key, "rule": existing}
            proposal = self._new_mapping_proposal(key, existing, mapping, "repeated_evidence_conflict")
            return {"action": "proposal_created", "proposal": proposal}

        rule = {**mapping, "source": "repeated_high_confidence", "source_txn_id": "",
                "created_at": _now(), "active": True}
        self.state["rules"][key] = rule
        self.state["history"].append({"event_id": _id("event", key), "event": "rule_added",
                                      "merchant_key": key, "before": None, "after": rule,
                                      "at": _now(), "rolled_back": False})
        self._save()
        self._audit({"event": "rule_added", "merchant_key": key, "mapping": mapping,
                     "source": "repeated_high_confidence", "observation_count": evidence["count"]})
        return {"action": "learned", "merchant_key": key, "rule": rule}

    def _new_mapping_proposal(self, key: str, before: dict[str, Any], after: dict[str, Any],
                              reason: str) -> dict[str, Any]:
        for proposal in self.state["proposals"].values():
            if (proposal.get("status") == "pending" and proposal.get("kind") == "mapping_overwrite"
                    and proposal.get("merchant_key") == key and proposal.get("after") == after):
                return proposal
        proposal_id = _id("proposal", key, reason)
        proposal = {"proposal_id": proposal_id, "kind": "mapping_overwrite", "status": "pending",
                    "merchant_key": key, "before": before, "after": after, "reason": reason,
                    "impact": {"rules_changed": 1}, "created_at": _now()}
        self.state["proposals"][proposal_id] = proposal
        self._save()
        self._audit({"event": "proposal_created", **proposal})
        return proposal

    def propose_taxonomy_change(self, kind: str, payload: dict[str, Any], *,
                                impacted_transactions: int) -> dict[str, Any]:
        if kind not in ALLOWED_TAXONOMY_CHANGES:
            raise ValueError(f"kind must be one of {sorted(ALLOWED_TAXONOMY_CHANGES)}")
        if impacted_transactions < 0:
            raise ValueError("impacted_transactions cannot be negative")
        proposal_id = _id("proposal", kind, json.dumps(payload, sort_keys=True))
        proposal = {"proposal_id": proposal_id, "kind": f"taxonomy_{kind}", "status": "pending",
                    "payload": payload, "impact": {"transactions": impacted_transactions},
                    "created_at": _now()}
        self.state["proposals"][proposal_id] = proposal
        self._save()
        self._audit({"event": "proposal_created", **proposal})
        return proposal

    def approve(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal: {proposal_id}")
        if proposal["status"] != "pending":
            return {"action": "noop_not_pending", "proposal": proposal}
        if proposal["kind"] == "mapping_overwrite":
            key = proposal["merchant_key"]
            before = self.state["rules"].get(key)
            after = {**proposal["after"], "source": "approved_overwrite", "source_txn_id": "",
                     "created_at": _now(), "active": True}
            self.state["rules"][key] = after
            self.state["history"].append({"event_id": _id("event", key), "event": "rule_updated",
                                          "merchant_key": key, "before": before, "after": after,
                                          "at": _now(), "rolled_back": False})
        else:
            self.state["taxonomy_events"].append({"proposal_id": proposal_id,
                                                   "kind": proposal["kind"],
                                                   "payload": proposal["payload"],
                                                   "approved_at": _now()})
        proposal["status"] = "approved"
        proposal["approved_at"] = _now()
        self._save()
        self._audit({"event": "proposal_approved", "proposal_id": proposal_id,
                     "kind": proposal["kind"]})
        return {"action": "approved", "proposal": proposal}

    def reject(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal: {proposal_id}")
        if proposal["status"] == "pending":
            proposal["status"] = "rejected"
            proposal["rejected_at"] = _now()
            self._save()
            self._audit({"event": "proposal_rejected", "proposal_id": proposal_id})
        return {"action": "rejected", "proposal": proposal}

    def rollback(self, event_id: str) -> dict[str, Any]:
        event = next((item for item in self.state["history"] if item["event_id"] == event_id), None)
        if not event:
            raise KeyError(f"Unknown event: {event_id}")
        if event.get("rolled_back"):
            return {"action": "noop_already_rolled_back", "event": event}
        key = event["merchant_key"]
        if event["before"] is None:
            self.state["rules"].pop(key, None)
        else:
            self.state["rules"][key] = event["before"]
        event["rolled_back"] = True
        event["rolled_back_at"] = _now()
        self._save()
        self._audit({"event": "rule_rolled_back", "event_id": event_id, "merchant_key": key})
        return {"action": "rolled_back", "merchant_key": key, "event": event}


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local adaptive merchant categories")
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    sub = parser.add_subparsers(dest="command", required=True)

    learn = sub.add_parser("learn", help="Learn from an explicit user correction")
    learn.add_argument("merchant")
    learn.add_argument("category")
    learn.add_argument("--subcategory", default="")
    learn.add_argument("--txn-id", default="")

    resolve_parser = sub.add_parser("resolve", help="Resolve using learned local rules")
    resolve_parser.add_argument("merchant")

    approve = sub.add_parser("approve", help="Approve a pending proposal")
    approve.add_argument("proposal_id")
    reject = sub.add_parser("reject", help="Reject a pending proposal")
    reject.add_argument("proposal_id")
    rollback = sub.add_parser("rollback", help="Rollback a rule event")
    rollback.add_argument("event_id")
    sub.add_parser("status", help="Print settings, rules, and pending proposals")

    args = parser.parse_args()
    store = AdaptiveCategoryStore(args.state)
    if args.command == "learn":
        result = store.learn_confirmed(args.merchant, args.category, args.subcategory,
                                       source_txn_id=args.txn_id)
    elif args.command == "resolve":
        result = store.resolve(args.merchant) or {"action": "not_found"}
    elif args.command == "approve":
        result = store.approve(args.proposal_id)
    elif args.command == "reject":
        result = store.reject(args.proposal_id)
    elif args.command == "rollback":
        result = store.rollback(args.event_id)
    else:
        result = {"settings": store.state["settings"], "rules": store.state["rules"],
                  "pending_proposals": [p for p in store.state["proposals"].values()
                                        if p["status"] == "pending"]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
