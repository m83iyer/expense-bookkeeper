from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "native/Moneta/Sources/Moneta/Theme.swift"
DASHBOARD = ROOT / "native/Moneta/Sources/Moneta/DashboardViews.swift"


def _luminance(rgb: tuple[float, float, float]) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _dark_role(source: str, role: str) -> tuple[float, float, float]:
    match = re.search(
        rf"static let {role} = adaptive\(.*?dark: NSColor\(srgbRed: ([0-9.]+), green: ([0-9.]+), blue: ([0-9.]+)",
        source,
        re.DOTALL,
    )
    assert match, f"missing adaptive dark value for {role}"
    return tuple(float(channel) for channel in match.groups())


def test_semantic_finance_colours_are_readable_in_dark_appearance() -> None:
    source = THEME.read_text(encoding="utf-8")
    system_dark_surface = (0.11, 0.11, 0.12)

    for role in ("forest", "amber", "teal", "coral", "olive", "violet", "sky", "clay"):
        assert _contrast(_dark_role(source, role), system_dark_surface) >= 4.5


def test_brand_fills_do_not_reuse_bright_dark_text_colours() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")

    assert ".background(MonetaTheme.brandFill" in source
    assert ".buttonStyle(.borderedProminent).tint(MonetaTheme.forest)" not in source
    assert "foregroundStyle(MonetaTheme.onBrand)" in source
    assert "private let palette = MonetaTheme.chartPalette" in source
    assert "Color(red:" not in source
