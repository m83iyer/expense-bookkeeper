#!/usr/bin/env python3
"""Shared capture pipeline for notification, webhook, SMS, and email adapters.

Adapters should hand raw transaction text to this module instead of building
ledger rows themselves. Unknown merchants are preserved as Review rows so the
user can correct them and teach MERCHANT_MASTER later.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from adaptive_categories import AdaptiveCategoryStore
from adapters.hermes_whatsapp import send_confirmation
from merchant_resolver import build_master_from_rows, load_master_from_csv, resolve
from parse_transaction import parse
from web_enrichment import enrich as enrich_merchant, has_token_overlap
from write_sheet import append_rows, open_spreadsheet, transaction_to_row


REVIEW_FALLBACK_CATEGORY = "Misc"
REVIEW_FALLBACK_SUBCATEGORY = "Other"
REVIEW_FALLBACK_PAIR = (
    REVIEW_FALLBACK_CATEGORY.casefold(),
    REVIEW_FALLBACK_SUBCATEGORY.casefold(),
)
DEFAULT_HISTORY_DB = Path("~/.expense-bookkeeper/state/dashboard.sqlite3").expanduser()


def _load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open() as f:
        return yaml.safe_load(f) or {}


def _active_taxonomy_pairs(sh, config: dict[str, Any]) -> set[tuple[str, str]]:
    category_tab = config.get("sheet", {}).get("categories_tab", "CATEGORIES")
    rows = sh.worksheet(category_tab).get_all_values()
    for header_index, row in enumerate(rows):
        normalized = [(cell or "").strip().lower() for cell in row]
        if "category" not in normalized or "subcategory" not in normalized:
            continue
        category_index = normalized.index("category")
        subcategory_index = normalized.index("subcategory")
        active_index = normalized.index("active") if "active" in normalized else None
        pairs: set[tuple[str, str]] = set()
        for data_row in rows[header_index + 1:]:
            if len(data_row) <= max(category_index, subcategory_index):
                continue
            if active_index is not None and len(data_row) > active_index:
                if str(data_row[active_index]).strip().lower() in {"false", "0", "no", "inactive"}:
                    continue
            category = str(data_row[category_index]).strip()
            subcategory = str(data_row[subcategory_index]).strip()
            if category and subcategory:
                pairs.add((category.casefold(), subcategory.casefold()))
        return pairs
    raise RuntimeError("CATEGORIES is missing Category/Subcategory headers")


def _validate_master_taxonomy(master, active_pairs: set[tuple[str, str]]) -> None:
    for merchant_key, mapping in master.by_key.items():
        category = str(mapping.get("category") or "").strip()
        subcategory = str(mapping.get("subcategory") or "").strip()
        if not category or not subcategory:
            raise RuntimeError(
                f"MERCHANT_MASTER mapping '{merchant_key}' is missing Category/Subcategory"
            )
        if (category.casefold(), subcategory.casefold()) not in active_pairs:
            raise RuntimeError(
                f"MERCHANT_MASTER mapping '{merchant_key}' uses a pair not present in active "
                f"CATEGORIES: {category} / {subcategory}"
            )


def _require_review_fallback(active_pairs: set[tuple[str, str]] | None) -> None:
    if active_pairs is not None and REVIEW_FALLBACK_PAIR not in active_pairs:
        raise RuntimeError(
            "CATEGORIES must contain the active review fallback pair: "
            f"{REVIEW_FALLBACK_CATEGORY} / {REVIEW_FALLBACK_SUBCATEGORY}"
        )


def _load_master(config: dict[str, Any]):
    master_csv = (
        config.get("categorization", {}).get("merchant_master_csv")
        or config.get("merchant_master_csv")
    )
    sh = None
    if master_csv:
        master_path = Path(master_csv).expanduser()
        if not master_path.exists():
            raise RuntimeError(f"Configured merchant master CSV does not exist: {master_path}")
        master = load_master_from_csv(master_path)
    elif config.get("sheet", {}).get("id"):
        # The Google Sheet is the normal source of truth. A configured local
        # CSV is an explicit override for offline or test installations.
        sh = open_spreadsheet(config)
        merchant_tab = config.get("sheet", {}).get("merchant_tab", "MERCHANT_MASTER")
        master = build_master_from_rows(sh.worksheet(merchant_tab).get_all_values())
    else:
        master = build_master_from_rows([["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"]])

    if config.get("sheet", {}).get("id"):
        sh = sh or open_spreadsheet(config)
        active_pairs = _active_taxonomy_pairs(sh, config)
        _validate_master_taxonomy(master, active_pairs)
    else:
        active_pairs = None

    adaptive_cfg = config.get("categorization", {}).get("adaptive", {})
    if adaptive_cfg.get("enabled", False):
        state_path = adaptive_cfg.get("state_path") or "~/.expense-bookkeeper/state/adaptive_categories.json"
        store = AdaptiveCategoryStore(state_path)
        store.configure(
            auto_promote_repeated=adaptive_cfg.get("auto_promote_repeated", False),
            minimum_observations=int(adaptive_cfg.get("minimum_observations", 3)),
            minimum_confidence=float(adaptive_cfg.get("minimum_confidence", 0.90)),
        )
        # Sheet/CSV mappings win. Local rules fill gaps and cannot overwrite
        # the user's explicit merchant master.
        for key, rule in store.state["rules"].items():
            if rule.get("active", True) and key not in master.by_key:
                rule_pair = (
                    str(rule.get("category") or "").strip().casefold(),
                    str(rule.get("subcategory") or "").strip().casefold(),
                )
                if active_pairs is not None and rule_pair not in active_pairs:
                    raise RuntimeError(
                        f"Adaptive mapping '{key}' is outside the active CATEGORIES taxonomy"
                    )
                master.by_key[key] = {
                    "category": rule.get("category", ""),
                    "subcategory": rule.get("subcategory", ""),
                    "merchant_clean": rule.get("merchant_clean") or key.title(),
                }
        master.keys_sorted = sorted(master.by_key, key=lambda key: (-len(key.split()), -len(key)))
    return master, active_pairs


def _load_local_history(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Read confirmed evidence from the disposable local dashboard mirror.

    Classification remains functional when the mirror is absent or stale; the
    curated merchant master is always evaluated first. This local-only lookup
    avoids an extra Google Sheets read on every capture.
    """
    categorization = config.get("categorization", {}) or {}
    if not categorization.get("history_intelligence", True):
        return []
    configured = (config.get("dashboard", {}) or {}).get("database_path")
    database = Path(
        os.environ.get("EXPENSE_BOOKKEEPER_DASHBOARD_DB") or configured or DEFAULT_HISTORY_DB
    ).expanduser()
    if not database.exists():
        return []
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT date, amount, merchant_clean, category, subcategory,
                       card_used AS card, source, status
                FROM transactions
                WHERE lower(status) = 'confirmed'
                """
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return []
    return [dict(row) for row in rows]


def transaction_payload_from_raw(
    raw: str,
    config: dict[str, Any] | None = None,
    *,
    source: str = "capture_adapter",
    person: str = "Household",
    history_rows: list[dict[str, Any]] | None = None,
    web_evidence: list[dict[str, Any]] | None = None,
    category_override: str = "",
    subcategory_override: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Parse + resolve one raw event into a ledger transaction dict.

    Unknown or vague merchants become Status=Review with fallback category
    Misc/Other. They are not dropped.
    """
    config = config or {}
    parsed = parse(raw)
    if not parsed.valid:
        active_pairs = None
        if config.get("sheet", {}).get("id"):
            _, active_pairs = _load_master(config)
        _require_review_fallback(active_pairs)
        merchant = parsed.merchant_raw or "Unknown Merchant"
        return {
            "date": parsed.date,
            "amount": parsed.amount,
            "currency": parsed.currency,
            "merchant_raw": merchant,
            "merchant_clean": merchant,
            "category": REVIEW_FALLBACK_CATEGORY,
            "subcategory": REVIEW_FALLBACK_SUBCATEGORY,
            "card": parsed.card,
            "source": source,
            "person": person,
            "status": "Review",
            "review_reason": parsed.error or "Could not parse complete transaction",
            "review_options": [],
            "learning_scope": "transaction_only",
            "hash": parsed.hash,
        }

    master, active_pairs = _load_master(config)
    if bool(category_override) != bool(subcategory_override):
        raise ValueError("Category and subcategory must be supplied together.")
    if category_override and subcategory_override:
        selected_pair = (category_override.casefold(), subcategory_override.casefold())
        if active_pairs is not None and selected_pair not in active_pairs:
            raise ValueError("The selected category and subcategory are not active in CATEGORIES.")
        return {
            "date": parsed.date,
            "amount": parsed.amount,
            "currency": parsed.currency,
            "merchant_raw": parsed.merchant_raw,
            "merchant_clean": parsed.merchant_raw,
            "category": category_override,
            "subcategory": subcategory_override,
            "card": parsed.card,
            "source": source,
            "person": person,
            "notes": notes,
            "status": "Confirmed",
            "review_reason": "",
            "review_options": [],
            "learning_scope": "transaction_only",
            "research_attempted": False,
            "hash": parsed.hash,
        }
    if history_rows is None:
        history_rows = _load_local_history(config)
    resolver_args = {
        "history_rows": history_rows,
        "amount": parsed.amount,
        "card": parsed.card,
        "date": parsed.date,
        "source": source,
    }
    decision = resolve(
        parsed.merchant_raw,
        master,
        web_evidence=web_evidence,
        **resolver_args,
    )
    if (
        web_evidence is None
        and decision.get("tier") == 3
        and config.get("categorization", {}).get("web_enrichment") == "always"
    ):
        enriched = enrich_merchant(parsed.merchant_raw, config)
        evidence = enriched.get("evidence", []) if enriched else []
        if evidence and has_token_overlap(parsed.merchant_raw, evidence):
            web_evidence = evidence
            decision = resolve(
                parsed.merchant_raw,
                master,
                web_evidence=web_evidence,
                **resolver_args,
            )
    category = (decision.get("category") or "").strip()
    subcategory = (decision.get("subcategory") or "").strip()
    review_reason = (decision.get("review_reason") or "").strip()
    if (
        active_pairs is not None
        and category
        and subcategory
        and (category.casefold(), subcategory.casefold()) not in active_pairs
    ):
        decision = {
            **decision,
            "category": "",
            "subcategory": "",
            "tier": 3,
            "confidence": "rejected-outside-taxonomy",
            "review_reason": (
                f"Resolved pair is not active in CATEGORIES: {category} / {subcategory}"
            ),
        }
        category = ""
        subcategory = ""
        review_reason = decision["review_reason"]
    status = "Confirmed"
    if decision.get("tier") == 3 or not category or not subcategory:
        _require_review_fallback(active_pairs)
        status = "Review"
        category = category or REVIEW_FALLBACK_CATEGORY
        subcategory = subcategory or REVIEW_FALLBACK_SUBCATEGORY
        review_reason = review_reason or "Unknown category captured for manual review"

    return {
        "date": parsed.date,
        "amount": parsed.amount,
        "currency": parsed.currency,
        "merchant_raw": parsed.merchant_raw,
        "merchant_clean": decision.get("merchant_clean") or parsed.merchant_raw,
        "category": category,
        "subcategory": subcategory,
        "card": parsed.card,
        "source": source,
        "person": person,
        "notes": notes,
        "status": status,
        "review_reason": review_reason,
        "review_options": decision.get("review_options") or [],
        "learning_scope": decision.get("learning_scope") or "merchant_default",
        "research_attempted": bool(decision.get("research_attempted")),
        "hash": parsed.hash,
    }


def process_raw_event(
    raw: str,
    config: dict[str, Any],
    *,
    source: str = "capture_adapter",
    dry_run: bool = False,
    category_override: str = "",
    subcategory_override: str = "",
    notes: str = "",
    history_rows: list[dict[str, Any]] | None = None,
    web_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = transaction_payload_from_raw(
        raw,
        config,
        source=source,
        category_override=category_override,
        subcategory_override=subcategory_override,
        notes=notes,
        history_rows=history_rows,
        web_evidence=web_evidence,
    )
    row = transaction_to_row(payload)
    # A setup that has not passed strict validation must never write live.
    effective_dry_run = dry_run or not bool(config.get("armed", False))
    appended = append_rows(config, [row], dry_run=effective_dry_run)
    confirmation = {"status": "not_configured"}
    if appended and not effective_dry_run and config.get("confirmation", {}).get("adapter") == "whatsapp_hermes":
        hermes_cfg = config.get("hermes", {}) or {}
        target_env = hermes_cfg.get("target_env") or "EXPENSE_BOOKKEEPER_HERMES_TARGET"
        event = {
            "event_id": payload.get("hash") or row[0],
            "timestamp": payload.get("date", ""),
            "amount": payload.get("amount", ""),
            "currency": payload.get("currency", ""),
            "merchant": payload.get("merchant_clean") or payload.get("merchant_raw", ""),
            "category": payload.get("category", ""),
            "subcategory": payload.get("subcategory", ""),
            "status": payload.get("status", ""),
            "review_reason": payload.get("review_reason", ""),
            "review_options": payload.get("review_options") or [],
            "learning_scope": payload.get("learning_scope") or "merchant_default",
            "research_attempted": bool(payload.get("research_attempted")),
        }
        try:
            confirmation = send_confirmation(
                event,
                target=os.environ.get(target_env, ""),
                state_dir=hermes_cfg.get("state_dir") or "~/.expense-bookkeeper/state/hermes",
                include_merchant=bool(hermes_cfg.get("include_merchant", False)),
            )
        except Exception as exc:
            # Messaging must not turn a committed ledger row into a failed
            # capture. The adapter can retry from its local delivery state.
            confirmation = {"status": "deferred", "reason": type(exc).__name__}
    return {"appended": appended, "transaction": payload, "row": row,
            "confirmation": confirmation, "dry_run": effective_dry_run}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--source", default="manual_capture")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = _load_config(args.config)
    result = process_raw_event(args.raw, cfg, source=args.source, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        txn = result["transaction"]
        print(f"{txn['status']}: {txn['merchant_raw']} {txn['currency']} {txn['amount']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
