#!/usr/bin/env python3
"""Optional, fail-soft Hermes relay for WhatsApp confirmations and commands.

Hermes is an edge adapter only. The ledger commits before this adapter runs,
and a delivery failure never rolls back or blocks the expense pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_STATE_DIR = Path.home() / ".expense-bookkeeper" / "state" / "hermes"
ALLOWED_EVENT_FIELDS = {
    "event_id", "timestamp", "amount", "currency", "merchant", "category",
    "subcategory", "status", "review_reason", "review_options",
    "learning_scope", "research_attempted",
}
_CHANGE_LAST = re.compile(r"^change\s+to\s+(?P<category>[\w &'-]+?)(?:\s*/\s*(?P<subcategory>[\w &'-]+))?$", re.I)
_CHANGE_MERCHANT = re.compile(r"^change\s+(?P<merchant>[\w .&'-]+?)\s+to\s+(?P<category>[\w &'-]+?)(?:\s*/\s*(?P<subcategory>[\w &'-]+))?$", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _load_delivery_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "sent": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_event(event: dict[str, Any]) -> dict[str, Any]:
    safe = {key: event[key] for key in ALLOWED_EVENT_FIELDS if key in event}
    if not safe.get("event_id"):
        material = json.dumps(safe, sort_keys=True, default=str)
        safe["event_id"] = hashlib.sha256(material.encode()).hexdigest()[:20]
    return safe


def format_confirmation(event: dict[str, Any], *, include_merchant: bool = True) -> str:
    safe = _safe_event(event)
    amount = safe.get("amount", "?")
    currency = safe.get("currency", "")
    merchant = str(safe.get("merchant", "Merchant")) if include_merchant else "Merchant hidden"
    category = str(safe.get("category") or "Needs review")
    subcategory = str(safe.get("subcategory") or "").strip()
    category_label = f"{category} / {subcategory}" if subcategory else category
    if str(safe.get("status") or "Confirmed").casefold() == "review":
        reason = str(safe.get("review_reason") or "Unknown merchant or category")
        lines = [
            f"Expense needs review: {currency} {amount} · {merchant}\n"
            f"Current bucket: {category_label}\n"
            f"Reason: {reason}\n"
            f"Ref: {safe['event_id']}"
        ]
        options = safe.get("review_options") or []
        if options:
            lines.append("\nSuggested choices — history and merchant research checked:")
            for index, option in enumerate(options[:3], start=1):
                option_category = str(option.get("category") or "Needs review")
                option_subcategory = str(option.get("subcategory") or "").strip()
                option_label = (
                    f"{option_category} / {option_subcategory}"
                    if option_subcategory else option_category
                )
                lines.append(f"{index}. {option_label}")
            lines.append("Reply 1, 2 or 3 — or: change to Category / Subcategory")
        else:
            lines.append("\nNo reliable reusable match remained after history and merchant research.")
            lines.append("Reply: change to Category / Subcategory")
        if str(safe.get("learning_scope") or "").casefold() == "transaction_only":
            lines.append("This choice applies only to this transaction; it will not teach a merchant rule.")
        return "\n".join(lines)
    return (f"Expense logged: {currency} {amount} · {merchant} · {category_label}\n"
            f"Ref: {safe['event_id']}\n"
            "Reply: change to Category / Subcategory")


def send_confirmation(event: dict[str, Any], *, target: str, state_dir: str | Path = DEFAULT_STATE_DIR,
                      hermes_bin: str = "hermes", include_merchant: bool = True,
                      dry_run: bool = False,
                      runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict[str, Any]:
    """Send once through Hermes. Returns status instead of raising on delivery errors."""
    if not target or not (target == "whatsapp" or target.startswith("whatsapp:")):
        return {"status": "disabled", "reason": "A user-owned WhatsApp target is not configured"}
    safe = _safe_event(event)
    event_id = str(safe["event_id"])
    state_path = Path(state_dir).expanduser() / "delivery_state.json"
    state = _load_delivery_state(state_path)
    if event_id in state.get("sent", {}):
        return {"status": "duplicate", "event_id": event_id}
    message = format_confirmation(safe, include_merchant=include_merchant)
    if dry_run:
        return {"status": "dry_run", "event_id": event_id, "message": message}

    try:
        completed = runner(
            [hermes_bin, "send", "--to", target, "--file", "-", "--json"],
            input=message,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "deferred", "event_id": event_id,
                "reason": f"Hermes unavailable: {type(exc).__name__}"}
    if completed.returncode != 0:
        return {"status": "deferred", "event_id": event_id,
                "reason": "Hermes delivery failed", "returncode": completed.returncode}

    state.setdefault("sent", {})[event_id] = {"sent_at": _now(), "target_kind": "whatsapp"}
    if len(state["sent"]) > 5000:
        newest = list(state["sent"].items())[-5000:]
        state["sent"] = dict(newest)
    _atomic_write(state_path, state)
    return {"status": "sent", "event_id": event_id}


def parse_inbound_command(message: str, *, txn_id: str = "") -> dict[str, Any] | None:
    """Parse a narrow correction command; arbitrary messages are ignored."""
    text = (message or "").strip()
    if text in {"1", "2", "3"} and txn_id:
        return {
            "version": 1,
            "kind": "review_option_selection",
            "txn_id": txn_id,
            "option": int(text),
            "received_at": _now(),
            "requires_bulk_confirmation": False,
        }
    match = _CHANGE_MERCHANT.match(text)
    if match:
        return {"version": 1, "kind": "named_merchant_correction",
                "merchant": match.group("merchant").strip(),
                "category": match.group("category").strip(),
                "subcategory": (match.group("subcategory") or "").strip(),
                "received_at": _now(), "requires_bulk_confirmation": True}
    match = _CHANGE_LAST.match(text)
    if match and txn_id:
        return {"version": 1, "kind": "transaction_correction", "txn_id": txn_id,
                "category": match.group("category").strip(),
                "subcategory": (match.group("subcategory") or "").strip(),
                "received_at": _now(), "requires_bulk_confirmation": False}
    return None


def queue_inbound_command(message: str, *, txn_id: str = "",
                          state_dir: str | Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    """Validate and append a command for the local correction worker."""
    command = parse_inbound_command(message, txn_id=txn_id)
    if not command:
        return {"status": "ignored", "reason": "Unsupported or ambiguous command"}
    queue_path = Path(state_dir).expanduser() / "inbound_commands.jsonl"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(command, sort_keys=True) + "\n")
    os.chmod(queue_path, 0o600)
    return {"status": "queued", "command": command, "queue_path": str(queue_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional Hermes WhatsApp adapter")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="Send a confirmation event JSON file")
    send.add_argument("event_json")
    send.add_argument("--target", default=os.environ.get("EXPENSE_BOOKKEEPER_HERMES_TARGET", ""))
    send.add_argument("--hide-merchant", action="store_true")
    send.add_argument("--dry-run", action="store_true")
    receive = sub.add_parser("receive", help="Queue a validated inbound correction")
    receive.add_argument("message")
    receive.add_argument("--txn-id", default="")
    args = parser.parse_args()

    if args.command == "send":
        event = json.loads(Path(args.event_json).read_text(encoding="utf-8"))
        result = send_confirmation(event, target=args.target, state_dir=args.state_dir,
                                   include_merchant=not args.hide_merchant, dry_run=args.dry_run)
    else:
        result = queue_inbound_command(args.message, txn_id=args.txn_id, state_dir=args.state_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] not in {"deferred"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
