"""SMS source adapter — generic, OS-agnostic.

Architecture:
  This module is a SOURCE adapter, not a parser. It takes raw SMS text + sender
  + timestamp from any SMS source (Mac chat.db reader / Android Tasker forward /
  Twilio webhook), identifies the bank from the sender, applies the user's
  bank-specific regex patterns, and delegates to parse_transaction.parse() so
  the rest of the pipeline (resolver, ledger, confirm) is untouched.

Why not parse here?
  parse_transaction.py owns the canonical schema (Transaction dataclass) and
  hashing convention (sha1, 16 chars). Reimplementing the schema here would
  cause drift. Bank-specific patterns are user config; the generic engine
  consumes them.

Where to wire your SMS source:
  See `sms_parser.md` recipe — covers Mac chat.db (sqlite read), Android
  via Tasker SMS-RECEIVED forward, and Twilio/MessageBird webhook receivers.

Schema invariant: returns a `parse_transaction.Transaction` instance with
source="SMS" set. Caller passes it through merchant_resolver → write_sheet
exactly like in-app push transactions.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
import sys

# Ensure the parent scripts/ dir is importable for parse_transaction
_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import parse_transaction  # noqa: E402


def _identify_bank(sender: str, text: str, bank_senders: dict[str, list[str]]) -> str | None:
    """Return the bank key whose sender_substrings match the SMS sender (or text fallback).

    `bank_senders` is the user-config dict mapping bank keys → list of sender substrings.
    Example user config:
        sms_bank_senders:
          wio:  ["wiopersonal", "wio personal", "wio bank"]
          enbd: ["emirates nbd", "emiratesnbd", "enbd"]
    """
    haystack = (sender + " " + text).lower()
    for bank_key, terms in bank_senders.items():
        for t in terms:
            if t.lower() in haystack:
                return bank_key
    return None


def feed_sms(
    text: str,
    sender: str,
    timestamp: datetime,
    user_config: dict,
) -> "parse_transaction.Transaction":
    """Process one SMS through the skill's parse pipeline.

    user_config keys consumed:
      sms_bank_senders     dict[str, list[str]]   bank → sender substrings
      sms_bank_patterns    dict[str, list[str]]   bank → list of regex strings
                                                   (named groups: amount, merchant,
                                                    optional currency / card / date)
      currency_default     str                    fallback currency (e.g. "AED")
      card_labels          dict[str, str]         bank → ledger Card_Used label

    Returns the Transaction (txn.valid will be False if no pattern matched —
    caller decides whether to log to skip queue).
    """
    bank_senders = user_config.get("sms_bank_senders", {}) or {}
    bank_patterns_cfg = user_config.get("sms_bank_patterns", {}) or {}
    currency_default = user_config.get("currency_default", "AED")
    card_labels = user_config.get("card_labels", {}) or {}

    bank_key = _identify_bank(sender, text, bank_senders)

    # Build the user_patterns list parse_transaction expects: list of (compiled_regex, label)
    user_patterns: list[tuple] = []
    if bank_key and bank_key in bank_patterns_cfg:
        for raw_pat in bank_patterns_cfg[bank_key]:
            try:
                user_patterns.append((re.compile(raw_pat, re.IGNORECASE), f"sms.{bank_key}"))
            except re.error:
                # Bad user regex — skip; caller's repair_diagnostics will surface it
                continue

    txn = parse_transaction.parse(text, user_patterns=user_patterns or None)

    # Stamp source + (best-effort) bank-specific defaults
    if hasattr(txn, "source"):
        txn.source = "SMS"
    else:
        # Older Transaction dataclass without `source` — store on a sidecar dict via setattr
        try:
            setattr(txn, "source", "SMS")
        except Exception:
            pass
    if not txn.currency:
        txn.currency = currency_default
    if bank_key and not txn.card:
        txn.card = card_labels.get(bank_key, bank_key)
    # Use SMS timestamp if parser didn't extract a date
    if not txn.date and timestamp:
        txn.date = timestamp.strftime("%Y-%m-%d")
        # Recompute hash now that date is set
        if txn.amount and txn.merchant_raw:
            txn.hash = parse_transaction._hash_for(txn.date, txn.amount, txn.merchant_raw)
            txn.valid = True

    return txn
