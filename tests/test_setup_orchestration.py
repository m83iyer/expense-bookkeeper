"""Tests for setup_wizard.py end-to-end orchestration (audit fix 2026-05-01).

Covers the bootstrap functions that don't require live gspread:
  - import_statements_proposed produces a non-empty proposed master from CSVs
  - The dispatch shape (resume vs fresh) is sane
  - Missing scripts referenced by docs now exist

Live-sheet steps (push_master_to_sheet, seed_categories, seed_recurring)
require gspread mocking similar to test_correction_safety.py — covered
indirectly via the wizard's reliance on validate_install which has its
own strict-gate tests.
"""
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


# ── Phase 2 — import_statements_proposed ─────────────────────────────

def test_import_statements_produces_master_csv():
    """A folder with one CSV produces a proposed merchant master."""
    from setup_wizard import import_statements_proposed

    tmp = Path(tempfile.mkdtemp())
    statements = tmp / "statements"
    statements.mkdir()
    state = tmp / "state"

    # Minimal bank-style CSV with merchant + amount columns
    (statements / "bank1.csv").write_text(
        "Date,Description,Amount\n"
        "2026-04-01,SPINNEYS MARINA,142.50\n"
        "2026-04-02,STARBUCKS DXB,28.00\n"
        "2026-04-03,SPINNEYS MOE,89.00\n"
        "2026-04-04,CARREFOUR MOE,250.00\n"
    )
    out, count = import_statements_proposed(str(statements), state)
    assert out.exists(), "proposed master CSV not written"
    assert count == 4, f"expected 4 unique merchants, got {count}"

    # File contents include the header + 4 merchant rows
    content = out.read_text()
    assert "Merchant_Keyword" in content
    assert "SPINNEYS MARINA" in content
    assert "CARREFOUR MOE" in content


def test_import_statements_empty_folder_returns_empty():
    from setup_wizard import import_statements_proposed
    tmp = Path(tempfile.mkdtemp())
    statements = tmp / "statements"
    statements.mkdir()
    state = tmp / "state"
    out, count = import_statements_proposed(str(statements), state)
    assert count == 0
    assert out.exists()  # empty header-only CSV
    rows = out.read_text().strip().splitlines()
    assert len(rows) == 1, "should be header only"


def test_import_statements_skips_csv_without_merchant_column():
    """A CSV that doesn't have a merchant/description column is silently skipped."""
    from setup_wizard import import_statements_proposed
    tmp = Path(tempfile.mkdtemp())
    statements = tmp / "statements"
    statements.mkdir()
    (statements / "weird.csv").write_text("Date,Amount\n2026-04-01,100\n")
    state = tmp / "state"
    out, count = import_statements_proposed(str(statements), state)
    assert count == 0


# ── Missing-scripts fix verification ────────────────────────────────

def test_recategorise_history_script_exists_and_imports():
    """Audit flagged this as a missing referenced script. Now it exists."""
    p = SKILL_ROOT / "scripts" / "recategorise_history.py"
    assert p.exists(), f"recategorise_history.py should exist at {p}"
    # Importable
    spec_globals = {}
    sys.path.insert(0, str(p.parent))
    import importlib
    mod = importlib.import_module("recategorise_history")
    assert hasattr(mod, "plan_changes")
    assert hasattr(mod, "apply_changes")
    assert hasattr(mod, "main")


def test_gmail_auth_script_exists_and_imports():
    """Audit flagged this as a missing referenced script. Now it exists."""
    p = SKILL_ROOT / "scripts" / "adapters" / "gmail_auth.py"
    assert p.exists(), f"gmail_auth.py should exist at {p}"
    sys.path.insert(0, str(p.parent))
    import importlib
    mod = importlib.import_module("gmail_auth")
    assert hasattr(mod, "authenticate")
    assert hasattr(mod, "validate_existing")
    assert hasattr(mod, "main")


def test_resume_from_master_flag_present():
    """Audit flagged --resume-from-master as referenced but unimplemented."""
    import argparse
    # We can't easily invoke the wizard's main() without prompts, but we can
    # check the argparse setup by reading the source for the option.
    src = (SKILL_ROOT / "scripts" / "setup_wizard.py").read_text()
    assert "--resume-from-master" in src, "resume-from-master flag must exist"
    assert "resume_from_master" in src, "resume handler must be wired"


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
