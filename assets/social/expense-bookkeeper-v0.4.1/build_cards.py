#!/usr/bin/env python3
"""Build deterministic v0.4.1 social evidence cards from synthetic outputs."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


CARD_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CARD_ROOT.parents[2]
SOURCE_DIR = CARD_ROOT / "source"
BASE_COMMIT = "2e69db9ffd7937a04cf1e6786e6b7c1dcb46801a"
WIDTH = 1600
HEIGHT = 2000

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from adaptive_categories import AdaptiveCategoryStore  # noqa: E402
from capture_pipeline import transaction_payload_from_raw  # noqa: E402
from write_sheet import transaction_to_row  # noqa: E402


CAPTURE_INPUT = "AED 155.40 spent on ExampleCard at XYZ123 UNKNOWN on 19/04/2026"
CAPTURE_IMAGE = CARD_ROOT / "card-a-capture-review.png"
CAPTURE_SOURCE = SOURCE_DIR / "card-a-capture-review.svg"
LEARNING_IMAGE = CARD_ROOT / "card-b-merchant-learning.png"
LEARNING_SOURCE = SOURCE_DIR / "card-b-merchant-learning.svg"
EVIDENCE_PATH = CARD_ROOT / "evidence.json"
MANIFEST_PATH = CARD_ROOT / "manifest.json"

ALT_TEXT = {
    "card-a-capture-review": (
        "Synthetic Expense Bookkeeper evidence card showing an AED 155.40 ExampleCard "
        "alert for XYZ123 UNKNOWN parsed into a retained review row. The visible result "
        "is category Misc, subcategory Other, status Review, with no personal data and "
        "no live ledger write."
    ),
    "card-b-merchant-learning": (
        "Synthetic Expense Bookkeeper evidence card showing Corner Cafe explicitly "
        "taught as Dining and Cafe, then CORNER CAFE DOWNTOWN resolved to the same local "
        "rule. Guardrails show auto-promotion off, conflicts requiring approval, rollback "
        "available, no live data, and no live ledger write."
    ),
}

COLORS = {
    "mint": "#EEF7EE",
    "mint_deep": "#DCECDD",
    "paper": "#FBFDF9",
    "white": "#FFFFFF",
    "navy": "#142236",
    "navy_soft": "#25364D",
    "teal": "#238480",
    "teal_dark": "#176966",
    "coral": "#CF5638",
    "coral_soft": "#F4D9CF",
    "gold": "#BB7B0B",
    "gold_soft": "#F3E6C7",
    "blue": "#3E70B5",
    "blue_soft": "#DCE8F6",
    "green": "#2D8A68",
    "green_soft": "#D8EBE1",
    "border": "#C5D9C6",
    "muted": "#5B6B7D",
    "faint": "#8B9AAA",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def capture_evidence() -> dict[str, Any]:
    transaction = transaction_payload_from_raw(
        CAPTURE_INPUT,
        {},
        source="synthetic_social_card",
        person="Synthetic",
    )
    row = transaction_to_row(transaction)
    expected = {
        "amount": 155.4,
        "currency": "AED",
        "merchant": "XYZ123 UNKNOWN",
        "category": "Misc",
        "subcategory": "Other",
        "status": "Review",
    }
    actual = {
        "amount": transaction["amount"],
        "currency": transaction["currency"],
        "merchant": transaction["merchant_clean"],
        "category": transaction["category"],
        "subcategory": transaction["subcategory"],
        "status": transaction["status"],
    }
    if actual != expected:
        raise RuntimeError(f"Capture evidence drifted: expected {expected!r}, got {actual!r}")
    if not row:
        raise RuntimeError("Synthetic transaction did not produce a retained row")
    return {
        "input": CAPTURE_INPUT,
        "result": {
            **actual,
            "review_required": True,
            "review_reason": transaction["review_reason"],
            "row_retained": True,
            "ledger_row_field_count": len(row),
        },
        "privacy": {
            "synthetic_only": True,
            "personal_data": False,
            "live_ledger_write": False,
            "credentials_accessed": False,
        },
    }


def learning_evidence() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".card-evidence-", dir=CARD_ROOT) as tmp:
        store = AdaptiveCategoryStore(Path(tmp) / "adaptive.json")
        learned = store.learn_confirmed(
            "Corner Cafe",
            "Dining",
            "Cafe",
            source_txn_id="synthetic-card-learning",
        )
        resolved = store.resolve("CORNER CAFE DOWNTOWN")
        conflict = store.learn_confirmed(
            "Corner Cafe",
            "Shopping",
            "Coffee",
            source_txn_id="synthetic-card-conflict",
        )
        mapping_after_conflict = store.resolve("CORNER CAFE DOWNTOWN")
        event_id = store.state["history"][-1]["event_id"]
        rollback = store.rollback(event_id)
        resolved_after_rollback = store.resolve("CORNER CAFE DOWNTOWN")

    expected_mapping = {
        "category": "Dining",
        "subcategory": "Cafe",
    }
    if learned["action"] != "learned":
        raise RuntimeError(f"Learning evidence drifted: {learned!r}")
    if not resolved or {
        "category": resolved["category"],
        "subcategory": resolved["subcategory"],
    } != expected_mapping:
        raise RuntimeError(f"Resolution evidence drifted: {resolved!r}")
    if conflict["action"] != "proposal_created":
        raise RuntimeError(f"Conflict evidence drifted: {conflict!r}")
    if not mapping_after_conflict or {
        "category": mapping_after_conflict["category"],
        "subcategory": mapping_after_conflict["subcategory"],
    } != expected_mapping:
        raise RuntimeError("A conflict silently replaced the confirmed mapping")
    if rollback["action"] != "rolled_back" or resolved_after_rollback is not None:
        raise RuntimeError("Rollback evidence drifted")

    return {
        "explicit_correction": {
            "merchant": "Corner Cafe",
            "category": "Dining",
            "subcategory": "Cafe",
            "action": "learned",
        },
        "next_variant": {
            "input": "CORNER CAFE DOWNTOWN",
            "matched_rule": "corner cafe",
            "category": "Dining",
            "subcategory": "Cafe",
            "resolved": True,
        },
        "guardrails": {
            "auto_promotion": False,
            "conflict_action": "proposal_created",
            "conflict_requires_approval": True,
            "mapping_unchanged_before_approval": True,
            "rollback_action": "rolled_back",
            "rollback_available": True,
        },
        "privacy": {
            "synthetic_temp_state": True,
            "personal_data": False,
            "live_ledger_write": False,
            "credentials_accessed": False,
        },
    }


def evidence_snapshot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_repository": "https://github.com/m83iyer/expense-bookkeeper",
        "source_commit": BASE_COMMIT,
        "capture_review": capture_evidence(),
        "merchant_learning": learning_evidence(),
    }


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def rect(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    fill: str,
    stroke: str = "none",
    stroke_width: int = 0,
    radius: int = 0,
) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
    )


def line(x1: int, y1: int, x2: int, y2: int, *, stroke: str, width: int = 3) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{stroke}" stroke-width="{width}"/>'
    )


def text(
    x: int,
    y: int,
    value: Any,
    *,
    size: int,
    color: str,
    weight: int = 500,
    family: str = "Avenir Next, Avenir, Helvetica Neue, sans-serif",
    anchor: str = "start",
    letter_spacing: float = 0,
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'letter-spacing="{letter_spacing}">{esc(value)}</text>'
    )


def multiline(
    x: int,
    y: int,
    lines: list[str],
    *,
    size: int,
    line_height: int,
    color: str,
    weight: int = 500,
    family: str = "Avenir Next, Avenir, Helvetica Neue, sans-serif",
    letter_spacing: float = 0,
) -> str:
    tspans = "".join(
        f'<tspan x="{x}" dy="{0 if index == 0 else line_height}">{esc(item)}</tspan>'
        for index, item in enumerate(lines)
    )
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}" letter-spacing="{letter_spacing}">'
        f"{tspans}</text>"
    )


def pill(
    x: int,
    y: int,
    width: int,
    label: str,
    *,
    fill: str,
    color: str,
    stroke: str = "none",
) -> str:
    return (
        rect(x, y, width, 52, fill=fill, stroke=stroke, stroke_width=2, radius=26)
        + text(
            x + width // 2,
            y + 35,
            label,
            size=20,
            color=color,
            weight=700,
            anchor="middle",
            family="SFMono-Regular, Menlo, monospace",
            letter_spacing=1.2,
        )
    )


def circle_label(x: int, y: int, label: str, *, fill: str) -> str:
    return (
        f'<circle cx="{x}" cy="{y}" r="31" fill="{fill}"/>'
        + text(
            x,
            y + 8,
            label,
            size=22,
            color=COLORS["white"],
            weight=700,
            anchor="middle",
            family="SFMono-Regular, Menlo, monospace",
        )
    )


def svg_shell(body: str, *, title: str, description: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">\n'
        f"<title id=\"title\">{esc(title)}</title>\n"
        f"<desc id=\"desc\">{esc(description)}</desc>\n"
        f"{body}\n</svg>\n"
    )


def capture_svg(evidence: dict[str, Any]) -> str:
    result = evidence["result"]
    c = COLORS
    chunks = [
        rect(0, 0, WIDTH, HEIGHT, fill=c["mint"]),
        rect(0, 0, WIDTH, 390, fill=c["navy"]),
        text(72, 70, "EXPENSE BOOKKEEPER  /  SYNTHETIC PROOF", size=22, color="#8DCBC2",
             weight=650, family="SFMono-Regular, Menlo, monospace", letter_spacing=1.4),
        text(1528, 70, "01 / 02", size=22, color="#AAB9C8", weight=600,
             anchor="end", family="SFMono-Regular, Menlo, monospace"),
        multiline(72, 178, ["UNKNOWN MERCHANT.", "ROW KEPT."], size=84, line_height=96,
                  color=c["white"], weight=780, letter_spacing=-1.5),
        text(72, 350, "Exact pipeline result • no category guessed", size=30,
             color="#A7D9D1", weight=520),
        pill(1190, 310, 338, "REVIEW REQUIRED", fill=c["coral"], color=c["white"]),
        rect(72, 430, 1456, 250, fill=c["paper"], stroke=c["border"], stroke_width=2,
             radius=28),
        text(112, 485, "SYNTHETIC ALERT INPUT", size=20, color=c["teal_dark"], weight=750,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1.6),
        multiline(112, 565, ["AED 155.40 spent on ExampleCard", "at XYZ123 UNKNOWN on 19/04/2026"],
                  size=38, line_height=52, color=c["navy"], weight=650),
        pill(1110, 472, 330, "NO PERSONAL DATA", fill=c["mint_deep"], color=c["teal_dark"]),
        rect(72, 720, 700, 280, fill=c["white"], stroke=c["border"], stroke_width=2,
             radius=28),
        text(112, 775, "PARSED AMOUNT", size=20, color=c["muted"], weight=700,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1.4),
        text(112, 900, f'{result["currency"]} {result["amount"]:.2f}', size=78,
             color=c["navy"], weight=800, letter_spacing=-1.5),
        text(112, 956, "Currency and amount parsed from the alert", size=25,
             color=c["muted"], weight=500),
        rect(808, 720, 720, 280, fill=c["coral_soft"], stroke="#E7B7A7", stroke_width=2,
             radius=28),
        text(848, 775, "DISPOSITION", size=20, color=c["coral"], weight=750,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1.4),
        text(848, 875, "REVIEW", size=70, color=c["coral"], weight=820),
        text(848, 935, "Row retained • human decision required", size=27,
             color=c["navy"], weight=620),
        rect(72, 1040, 1456, 420, fill=c["white"], stroke=c["border"], stroke_width=2,
             radius=28),
        text(112, 1100, "RETAINED ROW  /  EXACT FIELDS", size=21, color=c["teal_dark"],
             weight=750, family="SFMono-Regular, Menlo, monospace", letter_spacing=1.4),
        line(112, 1136, 1488, 1136, stroke=c["border"], width=2),
    ]
    rows = [
        ("MERCHANT", result["merchant"], c["navy"]),
        ("CATEGORY", result["category"], c["teal_dark"]),
        ("SUBCATEGORY", result["subcategory"], c["teal_dark"]),
        ("LEDGER DISPOSITION", "RETAINED", c["green"]),
    ]
    for index, (label, value, color) in enumerate(rows):
        y = 1205 + index * 62
        chunks.extend(
            [
                text(112, y, label, size=20, color=c["muted"], weight=650,
                     family="SFMono-Regular, Menlo, monospace", letter_spacing=1),
                text(650, y, value, size=30, color=color, weight=750),
                line(112, y + 25, 1488, y + 25, stroke="#E1EAE1", width=2),
            ]
        )
    chunks.extend(
        [
            rect(72, 1500, 1456, 205, fill=c["navy"], radius=28),
            text(112, 1555, "WHY THIS IS A VALID RESULT", size=20, color="#91D0C7",
                 weight=750, family="SFMono-Regular, Menlo, monospace", letter_spacing=1.5),
            text(112, 1625, "UNKNOWN ≠ DROPPED", size=42, color=c["white"], weight=790),
            multiline(710, 1584, ["The parser preserved the transaction, used the",
                                  "Misc / Other fallback, and surfaced uncertainty."],
                      size=27, line_height=39, color="#D9E3EC", weight=520),
            rect(72, 1745, 1456, 145, fill=c["paper"], stroke=c["border"], stroke_width=2,
                 radius=24),
            text(112, 1792, "PROOF BOUNDARY", size=18, color=c["coral"], weight=750,
                 family="SFMono-Regular, Menlo, monospace", letter_spacing=1.3),
            multiline(112, 1838, ["Deterministic synthetic input • no live sheet, credential, relay,",
                                  "or personal transaction accessed • NO LIVE LEDGER WRITE"],
                      size=23, line_height=32, color=c["navy"], weight=560),
            line(72, 1930, 1528, 1930, stroke=c["border"], width=2),
            text(72, 1970, "m83iyer / expense-bookkeeper", size=18, color=c["muted"],
                 weight=650, family="SFMono-Regular, Menlo, monospace"),
            text(1528, 1970, f"SOURCE {BASE_COMMIT[:8]}  •  v0.4.1", size=18,
                 color=c["muted"], weight=650, anchor="end",
                 family="SFMono-Regular, Menlo, monospace"),
        ]
    )
    return svg_shell(
        "".join(chunks),
        title="Expense Bookkeeper synthetic capture review evidence",
        description=ALT_TEXT["card-a-capture-review"],
    )


def guardrail_card(
    x: int,
    y: int,
    width: int,
    *,
    number: str,
    heading: str,
    lines: list[str],
    accent: str,
    soft: str,
) -> str:
    return "".join(
        [
            rect(x, y, width, 224, fill=COLORS["white"], stroke=COLORS["border"],
                 stroke_width=2, radius=26),
            rect(x, y, 12, 224, fill=accent, radius=6),
            circle_label(x + 62, y + 56, number, fill=accent),
            text(x + 112, y + 64, heading, size=24, color=COLORS["navy"], weight=780),
            rect(x + 34, y + 102, width - 68, 88, fill=soft, radius=18),
            multiline(x + 56, y + 137, lines, size=22, line_height=30,
                      color=COLORS["navy"], weight=560),
        ]
    )


def learning_svg(evidence: dict[str, Any]) -> str:
    correction = evidence["explicit_correction"]
    variant = evidence["next_variant"]
    c = COLORS
    chunks = [
        rect(0, 0, WIDTH, HEIGHT, fill=c["mint"]),
        rect(0, 0, WIDTH, 410, fill=c["navy"]),
        text(72, 70, "EXPENSE BOOKKEEPER  /  SYNTHETIC PROOF", size=22, color="#8DCBC2",
             weight=650, family="SFMono-Regular, Menlo, monospace", letter_spacing=1.4),
        text(1528, 70, "02 / 02", size=22, color="#AAB9C8", weight=600,
             anchor="end", family="SFMono-Regular, Menlo, monospace"),
        multiline(72, 170, ["ONE CORRECTION TAUGHT.", "THE NEXT VARIANT RESOLVED."],
                  size=66, line_height=82, color=c["white"], weight=780,
                  letter_spacing=-1.2),
        text(72, 370, "Local learning with visible approval and rollback boundaries",
             size=29, color="#A7D9D1", weight=520),
        rect(72, 450, 1456, 265, fill=c["paper"], stroke=c["border"], stroke_width=2,
             radius=28),
        text(112, 505, "EXPLICIT CORRECTION", size=20, color=c["teal_dark"], weight=750,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1.5),
        text(112, 600, correction["merchant"], size=54, color=c["navy"], weight=800),
        text(690, 600, "→", size=54, color=c["teal"], weight=700),
        rect(790, 535, 650, 104, fill=c["green_soft"], radius=22),
        text(835, 602, f'{correction["category"]}  /  {correction["subcategory"]}',
             size=42, color=c["teal_dark"], weight=780),
        text(112, 670, "Confirmed by the user • stored as a local merchant rule",
             size=25, color=c["muted"], weight=540),
        rect(72, 755, 1456, 310, fill=c["white"], stroke=c["border"], stroke_width=2,
             radius=28),
        text(112, 810, "NEXT VARIANT  /  RESOLUTION RECEIPT", size=20,
             color=c["blue"], weight=750, family="SFMono-Regular, Menlo, monospace",
             letter_spacing=1.5),
        text(112, 900, variant["input"], size=43, color=c["navy"], weight=790),
        pill(1138, 846, 302, "MATCHED LOCAL RULE", fill=c["blue_soft"], color=c["blue"]),
        line(112, 945, 1488, 945, stroke=c["border"], width=2),
        text(112, 1012, "MATCH", size=19, color=c["muted"], weight=700,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1),
        text(350, 1012, variant["matched_rule"], size=29, color=c["navy"], weight=720),
        text(760, 1012, "RESULT", size=19, color=c["muted"], weight=700,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1),
        text(970, 1012, f'{variant["category"]} / {variant["subcategory"]}',
             size=31, color=c["teal_dark"], weight=780),
        guardrail_card(72, 1110, 700, number="01", heading="AUTO-PROMOTION OFF",
                       lines=["Repeated observations do not become", "rules unless the user opts in."],
                       accent=c["teal"], soft=c["green_soft"]),
        guardrail_card(808, 1110, 720, number="02", heading="CONFLICTS REQUIRE APPROVAL",
                       lines=["A conflicting category creates a", "proposal; the trusted rule stays."],
                       accent=c["coral"], soft=c["coral_soft"]),
        guardrail_card(72, 1365, 700, number="03", heading="ROLLBACK AVAILABLE",
                       lines=["The learned rule was rolled back in", "a separate synthetic proof step."],
                       accent=c["gold"], soft=c["gold_soft"]),
        guardrail_card(808, 1365, 720, number="04", heading="LOCAL STATE ONLY",
                       lines=["No cloud model, live sheet, or", "personal transaction was used."],
                       accent=c["blue"], soft=c["blue_soft"]),
        rect(72, 1635, 1456, 235, fill=c["navy"], radius=28),
        text(112, 1690, "EVIDENCE CHAIN", size=20, color="#91D0C7", weight=750,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=1.5),
        multiline(112, 1750, ["CORRECT  →  LEARN LOCAL RULE  →  RESOLVE VARIANT",
                              "CONFLICT  →  WAIT FOR APPROVAL  •  ROLLBACK  →  RESTORE"],
                  size=28, line_height=48, color=c["white"], weight=690,
                  family="SFMono-Regular, Menlo, monospace"),
        text(112, 1840, "SYNTHETIC TEMP STATE  •  NO LIVE DATA  •  NO LIVE LEDGER WRITE",
             size=20, color="#A7D9D1", weight=650,
             family="SFMono-Regular, Menlo, monospace", letter_spacing=0.8),
        line(72, 1930, 1528, 1930, stroke=c["border"], width=2),
        text(72, 1970, "m83iyer / expense-bookkeeper", size=18, color=c["muted"],
             weight=650, family="SFMono-Regular, Menlo, monospace"),
        text(1528, 1970, f"SOURCE {BASE_COMMIT[:8]}  •  v0.4.1", size=18,
             color=c["muted"], weight=650, anchor="end",
             family="SFMono-Regular, Menlo, monospace"),
    ]
    return svg_shell(
        "".join(chunks),
        title="Expense Bookkeeper synthetic merchant learning evidence",
        description=ALT_TEXT["card-b-merchant-learning"],
    )


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise RuntimeError(f"{path} is not a PNG with an IHDR header")
    return struct.unpack(">II", data[16:24])


def render_svg(source: Path, target: Path) -> None:
    renderer = shutil.which("rsvg-convert")
    if not renderer:
        raise RuntimeError("rsvg-convert is required to render the committed SVG source")
    subprocess.run(
        [
            renderer,
            "--format=png",
            f"--width={WIDTH}",
            f"--height={HEIGHT}",
            f"--output={target}",
            str(source),
        ],
        check=True,
    )


def asset_record(identifier: str, image: Path, source: Path) -> dict[str, Any]:
    width, height = png_dimensions(image)
    return {
        "id": identifier,
        "image": image.name,
        "source": str(source.relative_to(CARD_ROOT)),
        "width": width,
        "height": height,
        "image_sha256": sha256(image),
        "source_sha256": sha256(source),
        "alt_text": ALT_TEXT[identifier],
    }


def build() -> None:
    evidence = evidence_snapshot()
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(canonical_json(evidence), encoding="utf-8")
    CAPTURE_SOURCE.write_text(
        capture_svg(evidence["capture_review"]),
        encoding="utf-8",
    )
    LEARNING_SOURCE.write_text(
        learning_svg(evidence["merchant_learning"]),
        encoding="utf-8",
    )
    render_svg(CAPTURE_SOURCE, CAPTURE_IMAGE)
    render_svg(LEARNING_SOURCE, LEARNING_IMAGE)

    with tempfile.TemporaryDirectory(prefix=".determinism-", dir=CARD_ROOT) as tmp:
        capture_repeat = Path(tmp) / CAPTURE_IMAGE.name
        learning_repeat = Path(tmp) / LEARNING_IMAGE.name
        render_svg(CAPTURE_SOURCE, capture_repeat)
        render_svg(LEARNING_SOURCE, learning_repeat)
        if sha256(capture_repeat) != sha256(CAPTURE_IMAGE):
            raise RuntimeError("Capture image is not deterministic across two local renders")
        if sha256(learning_repeat) != sha256(LEARNING_IMAGE):
            raise RuntimeError("Learning image is not deterministic across two local renders")

    manifest = {
        "schema_version": 1,
        "release": "expense-bookkeeper-v0.4.1-evidence-cards",
        "design_system": "stockcentric-artifact-v1",
        "source_repository": "https://github.com/m83iyer/expense-bookkeeper",
        "source_commit": BASE_COMMIT,
        "evidence_file": EVIDENCE_PATH.name,
        "evidence_sha256": sha256(EVIDENCE_PATH),
        "render": {
            "format": "PNG",
            "width": WIDTH,
            "height": HEIGHT,
            "renderer": "rsvg-convert",
            "local_repeat_sha_match": True,
        },
        "assets": [
            asset_record(
                "card-a-capture-review",
                CAPTURE_IMAGE,
                CAPTURE_SOURCE,
            ),
            asset_record(
                "card-b-merchant-learning",
                LEARNING_IMAGE,
                LEARNING_SOURCE,
            ),
        ],
        "privacy_boundary": (
            "Deterministic synthetic inputs and SSD temporary state only. No live ledger, "
            "credential, relay, personal identifier, or ~/.expense-tracker state was read "
            "or changed."
        ),
    }
    MANIFEST_PATH.write_text(canonical_json(manifest), encoding="utf-8")
    check()


def check() -> None:
    required = [
        CAPTURE_IMAGE,
        CAPTURE_SOURCE,
        LEARNING_IMAGE,
        LEARNING_SOURCE,
        EVIDENCE_PATH,
        MANIFEST_PATH,
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing social evidence assets: {missing}")

    expected_evidence = evidence_snapshot()
    committed_evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    if committed_evidence != expected_evidence:
        raise RuntimeError("Committed synthetic evidence no longer matches repository behavior")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["source_commit"] != BASE_COMMIT:
        raise RuntimeError("Manifest source revision drifted")
    if manifest["evidence_sha256"] != sha256(EVIDENCE_PATH):
        raise RuntimeError("Evidence SHA does not match the committed evidence file")
    for asset in manifest["assets"]:
        image = CARD_ROOT / asset["image"]
        source = CARD_ROOT / asset["source"]
        if png_dimensions(image) != (WIDTH, HEIGHT):
            raise RuntimeError(f"Unexpected dimensions for {image}")
        if asset["image_sha256"] != sha256(image):
            raise RuntimeError(f"Image SHA drifted for {image}")
        if asset["source_sha256"] != sha256(source):
            raise RuntimeError(f"SVG source SHA drifted for {source}")
    print(
        json.dumps(
            {
                "status": "passed",
                "source_commit": BASE_COMMIT,
                "assets": [
                    {
                        "id": asset["id"],
                        "image": asset["image"],
                        "sha256": asset["image_sha256"],
                        "dimensions": [asset["width"], asset["height"]],
                    }
                    for asset in manifest["assets"]
                ],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--render", action="store_true", help="Regenerate SVG, PNG, evidence, and manifest")
    mode.add_argument("--check", action="store_true", help="Verify committed files against current behavior")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        build()


if __name__ == "__main__":
    main()
