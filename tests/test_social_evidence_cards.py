import hashlib
import json
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARD_ROOT = ROOT / "assets" / "social" / "expense-bookkeeper-v0.4.1"
MANIFEST = json.loads((CARD_ROOT / "manifest.json").read_text(encoding="utf-8"))
EVIDENCE = json.loads((CARD_ROOT / "evidence.json").read_text(encoding="utf-8"))
VISUAL_QA = json.loads((CARD_ROOT / "visual-qa.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert header[12:16] == b"IHDR"
    return struct.unpack(">II", header[16:24])


def svg_text(path: Path) -> str:
    root = ET.parse(path).getroot()
    assert root.attrib["width"] == "1600"
    assert root.attrib["height"] == "2000"
    assert root.attrib["viewBox"] == "0 0 1600 2000"
    return " ".join("".join(root.itertext()).split())


def test_manifest_assets_have_exact_dimensions_and_hashes():
    assert MANIFEST["design_system"] == "stockcentric-artifact-v1"
    assert MANIFEST["source_commit"] == "2e69db9ffd7937a04cf1e6786e6b7c1dcb46801a"
    assert MANIFEST["render"]["local_repeat_sha_match"] is True
    assert len(MANIFEST["assets"]) == 2
    for asset in MANIFEST["assets"]:
        image = CARD_ROOT / asset["image"]
        source = CARD_ROOT / asset["source"]
        assert png_dimensions(image) == (1600, 2000)
        assert sha256(image) == asset["image_sha256"]
        assert sha256(source) == asset["source_sha256"]
        assert len(asset["alt_text"]) >= 120
    assert sha256(CARD_ROOT / "evidence.json") == MANIFEST["evidence_sha256"]
    qa_by_image = {item["image"]: item for item in VISUAL_QA["assets"]}
    assert VISUAL_QA["status"] == "passed"
    for asset in MANIFEST["assets"]:
        assert qa_by_image[asset["image"]]["sha256"] == asset["image_sha256"]
        assert all(qa_by_image[asset["image"]]["checks"].values())


def test_capture_card_matches_exact_synthetic_result_and_privacy_boundary():
    result = EVIDENCE["capture_review"]["result"]
    assert result["amount"] == 155.4
    assert result["currency"] == "AED"
    assert result["merchant"] == "XYZ123 UNKNOWN"
    assert result["category"] == "Misc"
    assert result["subcategory"] == "Other"
    assert result["status"] == "Review"
    assert result["review_required"] is True
    assert result["row_retained"] is True

    visible = svg_text(CARD_ROOT / "source" / "card-a-capture-review.svg")
    for label in (
        "AED 155.40",
        "ExampleCard",
        "XYZ123 UNKNOWN",
        "Misc",
        "Other",
        "REVIEW REQUIRED",
        "RETAINED",
        "NO PERSONAL DATA",
        "NO LIVE LEDGER WRITE",
    ):
        assert label in visible


def test_learning_card_matches_exact_synthetic_result_and_guardrails():
    evidence = EVIDENCE["merchant_learning"]
    assert evidence["explicit_correction"] == {
        "action": "learned",
        "category": "Dining",
        "merchant": "Corner Cafe",
        "subcategory": "Cafe",
    }
    assert evidence["next_variant"]["input"] == "CORNER CAFE DOWNTOWN"
    assert evidence["next_variant"]["matched_rule"] == "corner cafe"
    assert evidence["next_variant"]["category"] == "Dining"
    assert evidence["next_variant"]["subcategory"] == "Cafe"
    assert evidence["guardrails"]["auto_promotion"] is False
    assert evidence["guardrails"]["conflict_requires_approval"] is True
    assert evidence["guardrails"]["mapping_unchanged_before_approval"] is True
    assert evidence["guardrails"]["rollback_available"] is True

    visible = svg_text(CARD_ROOT / "source" / "card-b-merchant-learning.svg")
    for label in (
        "Corner Cafe",
        "Dining / Cafe",
        "CORNER CAFE DOWNTOWN",
        "AUTO-PROMOTION OFF",
        "CONFLICTS REQUIRE APPROVAL",
        "ROLLBACK AVAILABLE",
        "SYNTHETIC TEMP STATE",
        "NO LIVE DATA",
        "NO LIVE LEDGER WRITE",
    ):
        assert label in visible


def test_builder_check_replays_synthetic_evidence_without_writing_live_state():
    result = subprocess.run(
        [
            sys.executable,
            str(CARD_ROOT / "build_cards.py"),
            "--check",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "passed"' in result.stdout
