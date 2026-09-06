#!/usr/bin/env python3
"""Refresh and load the dashboard's local foreign-exchange snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SUPPORTED_CURRENCIES = ("USD", "INR", "GBP", "EUR", "AED")
DEFAULT_FX_PATH = Path("~/.expense-bookkeeper/state/dashboard_fx_rates.json").expanduser()
FRANKFURTER_API = "https://api.frankfurter.dev/v2/rates"


def _snapshot_path(config: dict[str, Any], override: Path | None = None) -> Path:
    configured = config.get("dashboard", {}).get("fx_rates_path")
    return (override or Path(configured or DEFAULT_FX_PATH)).expanduser()


def _validate_rates(base: str, rates: dict[str, Any]) -> dict[str, float]:
    base = base.upper()
    normalized: dict[str, float] = {base: 1.0}
    for code in SUPPORTED_CURRENCIES:
        value = 1.0 if code == base else rates.get(code)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"FX snapshot is missing a valid {base}/{code} rate.") from exc
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"FX snapshot contains an invalid {base}/{code} rate.")
        normalized[code] = number
    return normalized


def write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".fx-rates-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def refresh_snapshot(
    config: dict[str, Any],
    output: Path | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 10,
) -> dict[str, Any]:
    base = str(config.get("locale", {}).get("default_currency") or "USD").upper()
    if base not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Dashboard FX refresh supports {', '.join(SUPPORTED_CURRENCIES)}; base is {base}.")
    quotes = ",".join(code for code in SUPPORTED_CURRENCIES if code != base)
    url = f"{FRANKFURTER_API}?{urlencode({'base': base, 'quotes': quotes})}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "expense-bookkeeper/2.0"})
    with opener(request, timeout=timeout) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("FX provider returned an unexpected response.")
    raw_rates = {
        str(item.get("quote", "")).upper(): item.get("rate")
        for item in rows
        if isinstance(item, dict) and str(item.get("base", "")).upper() == base
    }
    rates = _validate_rates(base, raw_rates)
    dates = sorted({str(item.get("date")) for item in rows if isinstance(item, dict) and item.get("date")})
    if not dates:
        raise ValueError("FX provider response did not include a rate date.")
    payload = {
        "schema_version": 1,
        "base": base,
        "as_of": dates[-1],
        "rates": rates,
        "source": "Frankfurter blended central-bank reference rates",
        "source_url": "https://frankfurter.dev/",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "mode": "reference",
    }
    write_snapshot(_snapshot_path(config, output), payload)
    return payload


def load_snapshot(config: dict[str, Any], base: str) -> dict[str, Any]:
    base = base.upper()
    path = _snapshot_path(config)
    if not path.exists():
        return {
            "base": base,
            "as_of": None,
            "rates": {base: 1.0},
            "source": "No FX snapshot loaded",
            "source_url": None,
            "mode": "base-only",
            "path": str(path),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"FX snapshot is unreadable: {path}") from exc
    if str(payload.get("base", "")).upper() != base:
        raise ValueError(f"FX snapshot base {payload.get('base')} does not match dashboard base {base}.")
    payload = dict(payload)
    payload["rates"] = _validate_rates(base, payload.get("rates") or {})
    payload["path"] = str(path)
    return payload


def currency_context(config: dict[str, Any], base: str, requested: str) -> dict[str, Any]:
    snapshot = load_snapshot(config, base)
    requested = requested.upper() if requested else base.upper()
    rates = snapshot["rates"]
    quote = requested if requested in SUPPORTED_CURRENCIES and requested in rates else base.upper()
    available = [code for code in SUPPORTED_CURRENCIES if code in rates]
    return {
        "base": base.upper(),
        "quote": quote,
        "rate": rates[quote],
        "available": available,
        "as_of": snapshot.get("as_of"),
        "source": snapshot.get("source"),
        "source_url": snapshot.get("source_url"),
        "mode": snapshot.get("mode", "reference"),
    }


def main() -> None:
    from scripts.write_sheet import _load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("~/.expense-bookkeeper/config.yaml").expanduser())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = _load_config(args.config)
    payload = refresh_snapshot(config, args.output)
    print(json.dumps({"status": "ok", "base": payload["base"], "as_of": payload["as_of"],
                      "currencies": list(payload["rates"]), "output": str(_snapshot_path(config, args.output))}))


if __name__ == "__main__":
    main()
