"""Tests for validate_install.py strict mode (audit fix 2026-05-01).

Critical skipped gates MUST cause failure in strict mode.
Non-strict mode allows skips so the wizard can still report progress
during partial setup.

Uses subprocess to invoke the validator with --json so we get a clean
machine-readable result.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
VALIDATOR = SKILL_ROOT / "scripts" / "validate_install.py"


def _write_config(tmp: Path, *, sheet_id: str = "", sa_path: str = "/dev/null") -> Path:
    """Write a minimal valid-shape config.yaml. sheet_id="" → critical gates skip."""
    import yaml
    cfg = {
        "mode": "Set up a new tracker",
        "armed": False,
        "locale": {"country": "AE", "timezone": "Asia/Dubai", "default_currency": "AED",
                   "date_formats": ["%Y-%m-%d"]},
        "sheet": {
            "service_account_path": sa_path,
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


def _run_validator(config_path: Path, strict: bool) -> dict:
    cmd = [sys.executable, str(VALIDATOR), "--config", str(config_path), "--json",
           "--strict" if strict else "--non-strict"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return {"exit_code": proc.returncode, **json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def test_strict_fails_when_no_sheet_configured():
    """Critical-gate skip in strict mode → exit 1, ready_for_arm=False."""
    tmp = Path(tempfile.mkdtemp())
    cfg = _write_config(tmp, sheet_id="")  # blank → G3 skips → strict-fail
    result = _run_validator(cfg, strict=True)
    assert result["exit_code"] == 1, f"strict should fail: {result}"
    assert result["ready_for_arm"] is False, f"never arm without sheet: {result}"
    # G3 should be flagged failed (was skip, promoted to fail in strict)
    g3 = next(r for r in result["results"] if r["gate"] == "G3 Google Sheet accessible")
    assert g3["status"] == "fail", f"G3 should fail in strict mode: {g3}"


def test_non_strict_skips_when_no_sheet_configured():
    """Non-strict mode allows skips (used for partial-setup development)."""
    tmp = Path(tempfile.mkdtemp())
    cfg = _write_config(tmp, sheet_id="")
    result = _run_validator(cfg, strict=False)
    g3 = next(r for r in result["results"] if r["gate"] == "G3 Google Sheet accessible")
    assert g3["status"] == "skip", f"G3 should skip in non-strict: {g3}"
    # ready_for_arm still False because critical gates were skipped
    assert result["ready_for_arm"] is False


def test_strict_fails_when_service_account_json_missing():
    tmp = Path(tempfile.mkdtemp())
    bogus = tmp / "nope.json"
    cfg = _write_config(tmp, sheet_id="", sa_path=str(bogus))
    result = _run_validator(cfg, strict=True)
    assert result["exit_code"] == 1
    g2 = next(r for r in result["results"] if r["gate"] == "G2 service-account JSON reachable")
    assert g2["status"] == "fail", f"G2 should fail: {g2}"


def test_strict_fails_when_service_account_json_unreadable():
    tmp = Path(tempfile.mkdtemp())
    bad = tmp / "bad.json"
    bad.write_text("{ this is not json")
    cfg = _write_config(tmp, sheet_id="", sa_path=str(bad))
    result = _run_validator(cfg, strict=True)
    assert result["exit_code"] == 1
    g2 = next(r for r in result["results"] if r["gate"] == "G2 service-account JSON reachable")
    assert g2["status"] == "fail"


def test_critical_gates_marked_critical_in_results():
    """Sanity: the 4 critical gates are flagged as such in JSON output.
    Per re-audit 2026-05-01: G8 (row-build dry-run) is no longer critical;
    G8b (safe live-write proof) replaced it."""
    tmp = Path(tempfile.mkdtemp())
    cfg = _write_config(tmp)
    result = _run_validator(cfg, strict=False)
    critical_names = {
        "G3 Google Sheet accessible",
        "G4 EXPENSES tab has expected headers",
        "G4b MERCHANT_MASTER + CATEGORIES tabs present + headered",
        "G8b safe live-write proof (EXPENSES_TEST)",
    }
    for r in result["results"]:
        if r["gate"] in critical_names:
            assert r["critical"] is True, f"{r['gate']} should be marked critical"
        else:
            assert r["critical"] is False, f"{r['gate']} wrongly marked critical (was: {r['gate']})"


def test_word_boundary_safety_gate_present_and_passing():
    """G6b is the audit-driven gate proving no substring false positives."""
    tmp = Path(tempfile.mkdtemp())
    cfg = _write_config(tmp)
    result = _run_validator(cfg, strict=False)
    g6b = next(r for r in result["results"]
               if r["gate"].startswith("G6b word-boundary safety"))
    assert g6b["status"] == "pass", f"G6b must pass — substring safety: {g6b}"


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
