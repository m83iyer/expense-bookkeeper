"""Tests for service-account Drive quota error handling (discovered 2026-05-01
during attempted live install on a free-tier Gmail GCP project).

Background: Google service accounts on free-tier GCP / non-Workspace projects
cannot own Drive files. The Drive API returns 'storageQuotaExceeded' even when
the SA owns zero files. The wizard must detect this specifically and surface
a clear actionable message — not a generic 'failed to create sheet' that
sends the user chasing a non-existent quota leak.
"""
import sys
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


def test_is_sa_quota_error_recognises_canonical_message():
    """The exact text Google returns: 'The user's Drive storage quota has been exceeded.'"""
    from setup_wizard import _is_sa_quota_error
    assert _is_sa_quota_error("APIError: [403]: The user's Drive storage quota has been exceeded.")
    assert _is_sa_quota_error("Storage quota exceeded for this account")
    assert _is_sa_quota_error("storageQuotaExceeded")  # the JSON error code


def test_is_sa_quota_error_does_not_match_unrelated_errors():
    """Don't mis-categorise other 403s or unrelated errors."""
    from setup_wizard import _is_sa_quota_error
    assert not _is_sa_quota_error("APIError: [403]: insufficientPermissions")
    assert not _is_sa_quota_error("ConnectionError: timed out")
    assert not _is_sa_quota_error("KeyError: 'sheet'")
    assert not _is_sa_quota_error("rate limit exceeded")  # different "exceeded"
    assert not _is_sa_quota_error("")


def test_sa_email_from_path_extracts_client_email(tmp_path):
    """Extract client_email from a service-account JSON for the error message."""
    import json
    from setup_wizard import _sa_email_from_path
    sa_file = tmp_path / "fake_sa.json"
    sa_file.write_text(json.dumps({
        "type": "service_account",
        "client_email": "test-sa@example.com",
        "project_id": "example-project",
    }))
    assert _sa_email_from_path(str(sa_file)) == "test-sa@example.com"


def test_sa_email_from_path_handles_missing_file():
    from setup_wizard import _sa_email_from_path
    assert _sa_email_from_path("/nonexistent/path.json") == "(unknown)"


def test_step3_sheet_handles_quota_error_with_byos_fallthrough(tmp_path, capsys):
    """When _create_ledger raises the SA quota error, step3_sheet must:
      - NOT exit immediately (new: falls through to 'bring your own sheet' mode)
      - print the SA email so the user knows what to share the sheet with
      - if user then provides no sheet ID, exit with code 1
    """
    import json
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps({
        "type": "service_account",
        "client_email": "test-sa@example.com",
        "project_id": "example-project",
    }))

    import setup_wizard

    def fake_create_ledger(*args, **kwargs):
        raise Exception("APIError: [403]: The user's Drive storage quota has been exceeded.")

    # inputs: "no existing sheet" → title → empty sheet ID (triggers exit 1)
    with patch.object(setup_wizard, "_create_ledger", fake_create_ledger), \
         patch("builtins.input", side_effect=["2", "Test Sheet", ""]):
        try:
            setup_wizard.step3_sheet(str(sa_file), "user@example.com")
            raise AssertionError("step3_sheet should have exited")
        except SystemExit as e:
            assert e.code == 1, f"expected exit code 1 when no sheet ID provided, got {e.code}"

    captured = capsys.readouterr()
    assert "service-account Drive quota" in captured.out, \
        "must explain it's an SA quota issue specifically"
    assert "test-sa@example.com" in captured.out, \
        "must surface the SA email so user knows what to share the sheet with"
    assert "bring your own sheet" in captured.out.lower() or \
           "create a blank sheet" in captured.out.lower() or \
           "create an empty sheet" in captured.out.lower(), \
        "must explain the BYOS workaround path"


def test_setup_flow_doc_has_sa_quota_section():
    """references/setup-flow.md must document this limitation upfront so a
    user picks the workaround BEFORE hitting the error."""
    doc = (SKILL_ROOT / "references" / "setup-flow.md").read_text()
    assert "Service-account Drive quota" in doc, \
        "setup-flow.md must have a § Service-account Drive quota section"
    assert "storageQuotaExceeded" in doc, \
        "setup-flow.md must name the actual Google error code so users can search for it"
    assert "Connect to a sheet you already own" in doc, \
        "setup-flow.md must document the recommended workaround"


if __name__ == "__main__":
    failures = 0
    fns = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        try:
            # Tests that need pytest fixtures run via pytest only
            import inspect
            sig = inspect.signature(fn)
            if "tmp_path" in sig.parameters or "capsys" in sig.parameters:
                print(f"  ⏭️  {name} (needs pytest fixtures — skipped in __main__)")
                continue
            fn()
            print(f"  ✅ {name}")
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failures += 1
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            failures += 1
    runnable = sum(1 for _, fn in fns
                   if "tmp_path" not in inspect.signature(fn).parameters
                   and "capsys" not in inspect.signature(fn).parameters)
    print(f"\n{runnable - failures} passed · {failures} failed (pytest-fixture tests skipped)")
    sys.exit(0 if failures == 0 else 1)
