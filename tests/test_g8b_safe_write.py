"""Tests for re-audit blocker 3 (audit fix 2026-05-01 round 2):
  - G8 renamed to "row-build dry-run" — no longer claims write proof
  - G8b "safe live-write proof" added: append → read-back → delete on EXPENSES_TEST
  - G8b is critical in strict mode; G8 is not
  - In-process mock of gspread (no live API calls)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).parent.parent
VALIDATOR = SKILL_ROOT / "scripts" / "validate_install.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


# ── Source-level rename ───────────────────────────────────────────────

def test_g8_renamed_in_source():
    """G8 must no longer claim write proof in its name."""
    src = (SKILL_ROOT / "scripts" / "validate_install.py").read_text()
    assert '@gate("G8 row-build dry-run")' in src, \
        "G8 must be renamed to 'G8 row-build dry-run'"
    assert "G8 dry-run write" not in src, \
        "Old gate name 'G8 dry-run write' must be gone"


def test_g8b_added_in_source():
    """G8b safe live-write proof must exist as its own gate."""
    src = (SKILL_ROOT / "scripts" / "validate_install.py").read_text()
    assert '@gate("G8b safe live-write proof (EXPENSES_TEST)")' in src
    # Critical-gates set must include G8b, not G8
    assert '"G8b safe live-write proof (EXPENSES_TEST)"' in src
    # Old G8 critical entry must be gone
    assert '"G8 dry-run write"' not in src


def test_g8b_appears_in_results_as_critical():
    """When the validator runs in --json mode, G8b appears with critical=True
    and G8 appears with critical=False."""
    tmp = Path(tempfile.mkdtemp())
    cfg_path = _write_minimal_config(tmp, sheet_id="")
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--config", str(cfg_path), "--json", "--non-strict"],
        capture_output=True, text=True,
    )
    result = json.loads(proc.stdout)

    g8 = next(r for r in result["results"] if r["gate"] == "G8 row-build dry-run")
    g8b = next(r for r in result["results"] if r["gate"] == "G8b safe live-write proof (EXPENSES_TEST)")

    assert g8["critical"] is False, "G8 should NOT be critical anymore"
    assert g8b["critical"] is True, "G8b should be critical"


def test_g8b_skips_when_no_sheet_in_non_strict():
    """No sheet ID → G8b skips in non-strict mode (no live call possible)."""
    tmp = Path(tempfile.mkdtemp())
    cfg_path = _write_minimal_config(tmp, sheet_id="")
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--config", str(cfg_path), "--json", "--non-strict"],
        capture_output=True, text=True,
    )
    result = json.loads(proc.stdout)
    g8b = next(r for r in result["results"] if r["gate"].startswith("G8b"))
    assert g8b["status"] == "skip", f"G8b should skip without sheet: {g8b}"


def test_g8b_fails_in_strict_when_no_sheet():
    """G8b is critical → strict-mode skip becomes FAIL."""
    tmp = Path(tempfile.mkdtemp())
    cfg_path = _write_minimal_config(tmp, sheet_id="")
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--config", str(cfg_path), "--json", "--strict"],
        capture_output=True, text=True,
    )
    result = json.loads(proc.stdout)
    g8b = next(r for r in result["results"] if r["gate"].startswith("G8b"))
    assert g8b["status"] == "fail", f"G8b should fail in strict mode without sheet: {g8b}"
    assert result["ready_for_arm"] is False


def test_g8b_does_real_round_trip_when_sheet_available():
    """Direct call: G8b appends a sentinel row to EXPENSES_TEST, reads it
    back, deletes it. Uses an in-process mock spreadsheet so no live API."""
    # Reach into the validator module's gate registry
    import importlib.util
    spec = importlib.util.spec_from_file_location("validate_install", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Find the G8b gate function
    g8b_fn = None
    for name, fn in mod.GATES:
        if name.startswith("G8b"):
            g8b_fn = fn
            break
    assert g8b_fn is not None, "G8b gate not registered"

    # Mock gspread worksheet
    appended = []
    deleted = []

    class MockWS:
        def __init__(self):
            self._rows = [["banner"], ["Txn_ID", "Date", "Day", "Month-Year",
                          "Amount", "Currency", "Txn_Type", "Category", "Subcategory",
                          "Merchant_Raw", "Merchant_Clean", "Card_Used", "Source",
                          "Person", "Notes", "Status", "Review_Reason", "Hash"]]

        def append_rows(self, rows, value_input_option=None):
            for r in rows:
                self._rows.append(list(r))
                appended.append(r)

        def get_all_values(self):
            return [list(r) for r in self._rows]

        def delete_rows(self, row_idx):
            deleted.append(row_idx)
            self._rows.pop(row_idx - 1)

    class MockSheet:
        def __init__(self):
            self.ws = MockWS()
        def worksheet(self, name):
            assert name == "EXPENSES_TEST"
            return self.ws

    sheet = MockSheet()
    ctx = {
        "config": {
            "sheet": {
                "id": "fake-sheet-id",
                "service_account_path": "/dev/null",
            },
            "locale": {"default_currency": "USD"},
        },
        "_book": sheet,
    }

    ok, msg = g8b_fn(ctx)
    assert ok is True, f"G8b should pass with mock sheet: {msg}"
    assert len(appended) == 1, "exactly one row should be appended"
    assert appended[0][0].startswith("VALIDATE_"), \
        f"sentinel must start with VALIDATE_: {appended[0][0]}"
    assert len(deleted) == 1, "exactly one row should be deleted (cleanup)"


# ── helpers ───────────────────────────────────────────────────────────

def _write_minimal_config(tmp: Path, *, sheet_id: str = "") -> Path:
    import yaml
    cfg = {
        "mode": "Set up a new tracker",
        "armed": False,
        "locale": {"country": "US", "timezone": "America/New_York",
                   "default_currency": "USD", "date_formats": ["%m/%d/%Y"]},
        "sheet": {
            "service_account_path": "/dev/null",
            "id": sheet_id,
            "expenses_tab": "EXPENSES",
        },
        "statements": {"path": str(tmp / "statements")},
        "categorization": {"confidence_threshold": 0.75, "fail_closed": True, "web_enrichment": "ask"},
        "capture": {"adapter": "manual_only"},
        "confirmation": {"adapter": "none"},
    }
    p = tmp / "config.yaml"
    with open(p, "w") as f:
        yaml.safe_dump(cfg, f)
    return p


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
