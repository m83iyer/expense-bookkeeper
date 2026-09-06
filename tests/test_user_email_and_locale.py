"""Tests for re-audit blockers 1 + 2 (audit fix 2026-05-01 round 2):
  - Fresh sheet provisioning shares with the human user's email, not service account
  - Locale is captured from user, not silently defaulted to UAE/Dubai/AED
"""
import sys
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


# ── Blocker 1: human-email sharing ────────────────────────────────────

def test_create_ledger_share_with_is_human_email():
    """Source-level guarantee: setup_wizard.main passes user_email (human),
    not client_email (service account), to step3_sheet."""
    src = (SKILL_ROOT / "scripts" / "setup_wizard.py").read_text()
    # The fix: step3_sheet is called with user["user_email"], not creds["client_email"]
    assert 'step3_sheet(creds["service_account_path"], user["user_email"]' in src, \
        "step3_sheet must be called with the human user_email, not the service account client_email"
    # And step3_sheet's docstring/comment must reflect this
    assert "Fresh provisioning shares the new sheet with `user_email` (the human)" in src, \
        "step3_sheet docstring must explain it shares with the human, not service account"


def test_step2b_human_email_function_exists():
    """The new step2b function must exist and require an email."""
    import setup_wizard
    assert hasattr(setup_wizard, "step2b_human_email"), \
        "setup_wizard must expose step2b_human_email()"


def test_step2b_human_email_validates_format():
    """step2b should reject obviously-invalid emails. Mock input() to feed cases."""
    import setup_wizard
    # Valid email — accepted
    with patch("builtins.input", side_effect=["test@example.com"]):
        result = setup_wizard.step2b_human_email()
        assert result == {"user_email": "test@example.com"}

    # First attempt empty → rejected; second attempt invalid → rejected; third valid → accepted
    with patch("builtins.input", side_effect=["", "notanemail", "user@example.com"]):
        result = setup_wizard.step2b_human_email()
        assert result == {"user_email": "user@example.com"}


def test_create_ledger_share_call_in_source():
    """_create_ledger uses share_with parameter passed in (no hardcoded email)."""
    import setup_wizard
    import inspect
    src = inspect.getsource(setup_wizard._create_ledger)
    # Must use the share_with parameter
    assert "sh.share(share_with" in src, \
        "_create_ledger must share with the parameter, not a hardcoded address"


# ── Blocker 2: locale captured, not silently defaulted ───────────────

def test_step3b_locale_function_exists():
    """The new step3b_locale function must exist."""
    import setup_wizard
    assert hasattr(setup_wizard, "step3b_locale"), \
        "setup_wizard must expose step3b_locale()"


def test_step3b_locale_captures_non_uae():
    """Locale function must accept and persist non-UAE values."""
    import setup_wizard
    with patch("builtins.input", side_effect=[
        "GB",                # country
        "Europe/London",     # timezone
        "GBP",               # currency
        "%d/%m/%Y",          # date format
    ]):
        result = setup_wizard.step3b_locale()
    assert result["country"] == "GB"
    assert result["timezone"] == "Europe/London"
    assert result["default_currency"] == "GBP"
    assert result["date_formats"][0] == "%d/%m/%Y"


def test_step3b_locale_captures_us_format():
    """US locale: ISO codes + US date format."""
    import setup_wizard
    with patch("builtins.input", side_effect=[
        "US",
        "America/New_York",
        "USD",
        "%m/%d/%Y",
    ]):
        result = setup_wizard.step3b_locale()
    assert result["country"] == "US"
    assert result["timezone"] == "America/New_York"
    assert result["default_currency"] == "USD"
    assert result["date_formats"][0] == "%m/%d/%Y"


def test_step3b_locale_captures_india():
    """India locale: ISO codes + IST + INR."""
    import setup_wizard
    with patch("builtins.input", side_effect=[
        "IN",
        "Asia/Kolkata",
        "INR",
        "%d/%m/%Y",
    ]):
        result = setup_wizard.step3b_locale()
    assert result["country"] == "IN"
    assert result["timezone"] == "Asia/Kolkata"
    assert result["default_currency"] == "INR"


def test_no_hardcoded_uae_in_main_config():
    """Source-level: main() no longer writes a hardcoded locale dict."""
    src = (SKILL_ROOT / "scripts" / "setup_wizard.py").read_text()
    # Old hardcoded shape is gone
    assert '"country": "AE"' not in src, "Hardcoded country: AE must not appear in source"
    assert '"timezone": "Asia/Dubai"' not in src, "Hardcoded timezone: Asia/Dubai must not appear"
    assert '"default_currency": "AED"' not in src, "Hardcoded default_currency: AED must not appear"
    # New flow: locale comes from step3b_locale() return value
    assert 'locale = step3b_locale()' in src, "main() must call step3b_locale() to capture locale"
    assert '"locale": locale,' in src, "main() must put the captured locale into config"


# ── Blocker 7: requirements.txt has Gmail deps ────────────────────────

def test_requirements_txt_includes_gmail_deps():
    """gmail_auth.py imports google-auth-oauthlib and google-api-python-client.
    Both must be in requirements.txt so the default install works."""
    req_path = SKILL_ROOT / "requirements.txt"
    assert req_path.exists(), "requirements.txt must exist"
    content = req_path.read_text()
    assert "google-auth-oauthlib" in content, \
        "google-auth-oauthlib must be in requirements.txt for gmail_auth.py"
    assert "google-api-python-client" in content, \
        "google-api-python-client must be in requirements.txt for gmail_auth.py"


# ── Blocker 5: import script + setup_wizard reference correct file name ──

def test_import_statements_writes_correct_filename():
    """Should write merchant_master_proposed.csv, not the older
    merchant_master.csv or proposed_taxonomy.csv."""
    import import_statements, inspect
    src = inspect.getsource(import_statements)
    assert "merchant_master_proposed.csv" in src, \
        "import_statements.py must write merchant_master_proposed.csv"
    # Old file names must not appear in the generated output line
    # (the comment in the docstring may mention them as deprecated)
    out_lines = [l for l in src.splitlines() if "out_master =" in l]
    assert any("merchant_master_proposed.csv" in l for l in out_lines), \
        f"out_master assignment must use merchant_master_proposed.csv: {out_lines}"
    # proposed_taxonomy.csv must not appear in any active code path
    code_only = "\n".join(l for l in src.splitlines()
                          if not l.lstrip().startswith("#")
                          and "deprecated" not in l.lower()
                          and "outdated" not in l.lower()
                          and "older" not in l.lower())
    assert "proposed_taxonomy.csv" not in code_only, \
        "proposed_taxonomy.csv must not appear in active code"


if __name__ == "__main__":
    failures = 0
    fns = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failures += 1
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            failures += 1
    print(f"\n{len(fns) - failures} passed · {failures} failed")
    sys.exit(0 if failures == 0 else 1)
