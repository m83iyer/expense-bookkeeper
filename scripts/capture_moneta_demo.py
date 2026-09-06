#!/usr/bin/env python3
"""Capture privacy-safe Moneta launch artifacts in a real Chromium browser."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import Page, sync_playwright

from dashboard.demo import build_demo
from dashboard.server import Dashboard, Handler


PUBLIC_CAPTURES = (
    ("01-overview-usd.png", "overview", "USD", ""),
    ("02-drivers-inr.png", "drivers", "INR", ""),
    ("03-root-cause-aed.png", "drivers", "AED", ""),
    ("04-commitments-eur.png", "commitments", "EUR", ""),
    ("05-evidence-gbp.png", "ledger", "GBP", "&category=Travel"),
)


def _ready(page: Page) -> None:
    page.wait_for_function("document.body.classList.contains('ready')")
    page.wait_for_function("document.fonts ? document.fonts.status === 'loaded' : true")
    if not page.locator("#errorState").is_hidden():
        raise RuntimeError(page.locator("#errorState").inner_text())
    if not page.locator("#demoBadge").is_visible():
        raise RuntimeError("Synthetic demo badge is not visible.")
    if page.locator("#periodSpend").inner_text().strip() == "—":
        raise RuntimeError("Dashboard totals did not render.")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if overflow > 1:
        raise RuntimeError(f"Horizontal overflow detected: {overflow}px")


def _open(page: Page, origin: str, view: str, currency: str, extra_query: str = "") -> None:
    page.goto(
        f"{origin}/?view={view}&currency={currency}&month=Aug-2026&range=3&comparison=previous{extra_query}",
        wait_until="networkidle",
    )
    _ready(page)
    page.evaluate("document.documentElement.style.scrollBehavior='auto'; document.body.style.scrollBehavior='auto'")
    page.wait_for_timeout(80)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(80)
    button = page.locator(f'#currencyToggle button[data-currency="{currency}"]')
    if button.get_attribute("aria-pressed") != "true":
        raise RuntimeError(f"{currency} currency state did not settle.")


def _reset_to_top(page: Page) -> None:
    page.evaluate(
        """() => {
          const style = document.createElement('style');
          style.id = 'moneta-capture-lock';
          style.textContent = `
            html, body { overflow: hidden !important; }
            .app-shell { position: fixed !important; inset: 0 !important; overflow: hidden !important; }
            .rail { position: relative !important; }
            .workspace { height: 900px !important; overflow: hidden !important; }
          `;
          document.querySelector('#moneta-capture-lock')?.remove();
          document.head.appendChild(style);
        }"""
    )
    page.evaluate("window.scrollTo(0, 0)")
    # DOM geometry updates before Chromium's compositor has necessarily painted
    # the same frame. Two animation frames plus a quiet hold make the pixels and
    # the bounding-box assertions describe the same visual state.
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    page.wait_for_timeout(500)
    frame = page.evaluate(
        """() => ({
          windowScrollY: window.scrollY,
          documentScrollTop: document.scrollingElement?.scrollTop ?? null,
          visualPageTop: window.visualViewport?.pageTop ?? null,
          brandTop: document.querySelector('.brand')?.getBoundingClientRect().top ?? null,
          headlineTop: document.querySelector('#viewQuestion')?.getBoundingClientRect().top ?? null,
          scopeTop: document.querySelector('.scope-bar')?.getBoundingClientRect().top ?? null,
        })"""
    )
    if any(frame[key] != 0 for key in ("windowScrollY", "documentScrollTop", "visualPageTop")):
        raise RuntimeError(f"Top-of-view capture retained scroll state: {frame}.")
    if frame["brandTop"] is None or frame["brandTop"] < 20:
        raise RuntimeError(f"Brand is clipped in top-of-view capture: {frame}.")
    if frame["headlineTop"] is None or frame["headlineTop"] < 55:
        raise RuntimeError(f"Headline is clipped in top-of-view capture: {frame}.")
    if frame["scopeTop"] is None or frame["scopeTop"] < 220:
        raise RuntimeError(f"Scope bar is clipped in top-of-view capture: {frame}.")


def _select_root_cause(page: Page) -> None:
    travel = page.locator("#driverMatrix .matrix-row").filter(has_text="Travel").first
    travel.click()
    accommodation = page.locator("#driverMatrix .matrix-row").filter(has_text="Accommodation").first
    accommodation.click()
    airbnb = page.locator("#driverMatrix .matrix-row").filter(has_text="Airbnb").first
    airbnb.click()
    page.wait_for_timeout(200)
    if "Airbnb" not in page.locator("#driverEvidenceTitle").inner_text():
        raise RuntimeError("Merchant evidence did not resolve to Airbnb.")
    page.locator(".matrix-panel").evaluate("element => element.scrollIntoView({block:'start', behavior:'auto'})")
    page.evaluate("window.scrollBy(0, -12)")
    page.mouse.move(2, 2)
    page.wait_for_timeout(80)


def capture(output: Path) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime = output.parent / "browser-runtime"
    demo = build_demo(runtime)
    dashboard = Dashboard(Path(demo["config"]), Path(demo["database"]))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.dashboard = dashboard
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    console_errors: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for filename, view, currency, extra_query in PUBLIC_CAPTURES:
                # A fresh context prevents browser scroll restoration from leaking
                # between public assets. Each image must prove its own framing.
                context = browser.new_context(
                    viewport={"width": 1600, "height": 900}, device_scale_factor=1, reduced_motion="reduce"
                )
                page = context.new_page()
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.on("pageerror", lambda error: console_errors.append(str(error)))
                _open(page, origin, view, currency, extra_query)
                if filename == "03-root-cause-aed.png":
                    _select_root_cause(page)
                else:
                    _reset_to_top(page)
                path = output / filename
                page.screenshot(path=str(path), full_page=False, animations="disabled")
                if filename != "03-root-cause-aed.png":
                    _reset_to_top(page)
                records.append({
                    "file": filename,
                    "view": view,
                    "currency": currency,
                    "width": 1600,
                    "height": 900,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
                page.close()
                context.close()

            mobile_dir = output / "responsive-proof"
            mobile_dir.mkdir(exist_ok=True)
            mobile = browser.new_context(
                viewport={"width": 390, "height": 844}, device_scale_factor=1, reduced_motion="reduce"
            )
            mobile_page = mobile.new_page()
            mobile_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            mobile_page.on("pageerror", lambda error: console_errors.append(str(error)))
            _open(mobile_page, origin, "overview", "USD")
            mobile_page.screenshot(path=str(mobile_dir / "mobile-overview-usd.png"), full_page=False)
            mobile.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    if console_errors:
        raise RuntimeError(f"Browser console errors: {console_errors}")
    if len(records) != 5 or len({item["sha256"] for item in records}) != 5:
        raise RuntimeError("Expected five distinct public screenshots.")
    report = {
        "schema": "moneta_visual_proof_v1",
        "status": "green",
        "synthetic_demo": True,
        "public_captures": records,
        "responsive_capture": "responsive-proof/mobile-overview-usd.png",
        "console_errors": [],
    }
    (output / "visual-proof.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(capture(args.output), indent=2))


if __name__ == "__main__":
    main()
