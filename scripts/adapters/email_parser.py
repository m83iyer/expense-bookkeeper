"""Email source adapter — generic, OS-agnostic.

Same architecture as sms_parser.py: this module is a SOURCE, not a parser.
Takes raw email body + sender + timestamp from any email source (Gmail API
poll / IMAP fetch / forwarder webhook), identifies the bank from sender or
subject, applies user-configured regex patterns, delegates parsing to
parse_transaction.parse().

Pair with `email_gmail.md` recipe for Gmail-API setup, or wire any IMAP /
forwarder source. The pipeline (resolver, ledger, confirm) is untouched.

Schema invariant: returns a `parse_transaction.Transaction` with
source="Email" set.
"""
from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import sys

_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import parse_transaction  # noqa: E402


class _EmailHTMLTextExtractor(HTMLParser):
    """Extract visible text while ignoring active and styling content."""

    _IGNORED_ELEMENTS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._IGNORED_ELEMENTS:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._IGNORED_ELEMENTS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(self._parts)


def _identify_bank(sender: str, subject: str, body: str,
                   bank_senders: dict[str, list[str]]) -> str | None:
    """Match the email's sender / subject / body against user-config bank substrings."""
    haystack = (sender + " " + subject + " " + body[:500]).lower()
    for bank_key, terms in bank_senders.items():
        for t in terms:
            if t.lower() in haystack:
                return bank_key
    return None


def _strip_html(s: str) -> str:
    """Extract visible text from an HTML email using the standard parser."""
    parser = _EmailHTMLTextExtractor()
    parser.feed(s)
    parser.close()
    return re.sub(r"\s+", " ", parser.text()).strip()


def feed_email(
    body: str,
    sender: str,
    subject: str,
    timestamp: datetime,
    user_config: dict,
    is_html: bool = False,
) -> "parse_transaction.Transaction":
    """Process one email through the skill's parse pipeline.

    user_config keys consumed:
      email_bank_senders   dict[str, list[str]]  bank → sender/subject substrings
      email_bank_patterns  dict[str, list[str]]  bank → list of regex strings
      currency_default     str                   fallback currency
      card_labels          dict[str, str]        bank → ledger Card_Used label
    """
    bank_senders = user_config.get("email_bank_senders", {}) or {}
    bank_patterns_cfg = user_config.get("email_bank_patterns", {}) or {}
    currency_default = user_config.get("currency_default", "AED")
    card_labels = user_config.get("card_labels", {}) or {}

    text = _strip_html(body) if is_html else body

    bank_key = _identify_bank(sender, subject, text, bank_senders)

    user_patterns: list[tuple] = []
    if bank_key and bank_key in bank_patterns_cfg:
        for raw_pat in bank_patterns_cfg[bank_key]:
            try:
                user_patterns.append((re.compile(raw_pat, re.IGNORECASE | re.DOTALL),
                                      f"email.{bank_key}"))
            except re.error:
                continue

    txn = parse_transaction.parse(text, user_patterns=user_patterns or None)

    if hasattr(txn, "source"):
        txn.source = "Email"
    else:
        try:
            setattr(txn, "source", "Email")
        except Exception:
            pass
    if not txn.currency:
        txn.currency = currency_default
    if bank_key and not txn.card:
        txn.card = card_labels.get(bank_key, bank_key)
    if not txn.date and timestamp:
        txn.date = timestamp.strftime("%Y-%m-%d")
        if txn.amount and txn.merchant_raw:
            txn.hash = parse_transaction._hash_for(txn.date, txn.amount, txn.merchant_raw)
            txn.valid = True

    return txn
