from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "assets" / "social" / "expense-bookkeeper-v2.0.0"
MANIFEST = json.loads((ASSET_ROOT / "manifest.json").read_text(encoding="utf-8"))
EVIDENCE = json.loads((ASSET_ROOT / "evidence.json").read_text(encoding="utf-8"))
VISUAL_QA = json.loads((ASSET_ROOT / "visual-qa.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert header[12:16] == b"IHDR"
    return struct.unpack(">II", header[16:24])


def test_moneta_launch_gallery_is_exact_and_synthetic():
    assert MANIFEST["release"] == "expense-bookkeeper-v2.0.0-moneta"
    assert MANIFEST["source_commit"] == "7cb3ad31a6353016ec16e5b7745710f03fe2a389"
    assert MANIFEST["source_cloud_run"] == 33360747571
    assert MANIFEST["synthetic_demo"] is True
    assert len(MANIFEST["assets"]) == 4
    assert {item["currency"] for item in MANIFEST["assets"]} == {"USD", "AED", "EUR", "GBP"}

    committed_pngs = {path.name for path in ASSET_ROOT.glob("*.png")}
    declared_pngs = {item["image"] for item in MANIFEST["assets"]}
    assert committed_pngs == declared_pngs
    for asset in MANIFEST["assets"]:
        image = ASSET_ROOT / asset["image"]
        assert png_dimensions(image) == (1600, 900)
        assert sha256(image) == asset["sha256"]


def test_human_visual_review_rejects_the_unstable_fifth_capture():
    assert EVIDENCE["status"] == "passed"
    assert EVIDENCE["cloud_release_gate"]["status"] == "success"
    assert EVIDENCE["cloud_release_gate"]["python_versions"] == ["3.10", "3.12", "3.14"]
    assert EVIDENCE["human_visual_decision"]["rejected"] == ["02-drivers-inr.png"]
    assert VISUAL_QA["status"] == "passed"
    assert VISUAL_QA["rejected_capture"]["image"] not in {
        item["image"] for item in MANIFEST["assets"]
    }
    qa_by_image = {item["image"]: item for item in VISUAL_QA["assets"]}
    for asset in MANIFEST["assets"]:
        assert qa_by_image[asset["image"]]["sha256"] == asset["sha256"]
        assert all(qa_by_image[asset["image"]]["checks"].values())


def test_alt_text_and_privacy_boundary_are_explicit():
    alt_text = (ASSET_ROOT / "ALT_TEXT.md").read_text(encoding="utf-8")
    for phrase in ("Synthetic Moneta", "no personal expense data", "Google Sheets"):
        assert phrase in alt_text
    privacy = MANIFEST["privacy_boundary"]
    for forbidden_live_surface in ("No live ledger", "credential", "personal identifier"):
        assert forbidden_live_surface in privacy
