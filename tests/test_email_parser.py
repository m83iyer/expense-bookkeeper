from datetime import datetime
from pathlib import Path
import sys


ADAPTERS = Path(__file__).resolve().parents[1] / "scripts" / "adapters"
if str(ADAPTERS) not in sys.path:
    sys.path.insert(0, str(ADAPTERS))

from email_parser import _strip_html, feed_email  # noqa: E402


def test_strip_html_extracts_visible_text_and_decodes_entities():
    body = "<p>Paid&nbsp;AED 12.50 at Tom &amp; Serg</p>"

    assert _strip_html(body) == "Paid AED 12.50 at Tom & Serg"


def test_strip_html_ignores_script_and_style_content():
    body = (
        "<style>.amount { display: none; }</style>"
        "<p>AED 40 at Market</p>"
        "<script>alert('fake transaction')</script>"
    )

    assert _strip_html(body) == "AED 40 at Market"


def test_strip_html_handles_script_end_tag_with_whitespace():
    body = "<p>AED 40 at Market</p><script>alert(1)</script >"

    assert _strip_html(body) == "AED 40 at Market"


def test_feed_email_parses_html_transaction():
    txn = feed_email(
        body="<p>Charge of AED 82.75 at Sample Market — 16 Jul 2026</p>",
        sender="bank-alerts",
        subject="Card alert",
        timestamp=datetime(2026, 7, 16, 12, 0),
        user_config={},
        is_html=True,
    )

    assert txn.amount == 82.75
    assert txn.merchant_raw == "Sample Market"
    assert txn.source == "Email"
