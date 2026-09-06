#!/usr/bin/env python3
"""Poll Gmail for bank alert emails and pass message text to capture_pipeline."""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import yaml

THIS = Path(__file__).resolve()
SCRIPTS = THIS.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capture_pipeline import process_raw_event  # noqa: E402


def _load_config(path: str | Path) -> dict:
    with Path(path).expanduser().open() as f:
        return yaml.safe_load(f) or {}


def _state_path(cfg: dict) -> Path:
    raw = cfg.get("capture", {}).get("gmail", {}).get("state_file") or "~/.expense-bookkeeper/state/gmail_last_seen.json"
    return Path(raw).expanduser()


def _load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()).get("seen_message_ids", []))
    except Exception:
        return set()


def _save_seen(path: Path, seen: set[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen_message_ids": sorted(seen)[-1000:]}, indent=2))


def _body_from_payload(payload: dict) -> str:
    chunks: list[str] = []

    def walk(part: dict):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime in {"text/plain", "text/html"}:
            chunks.append(base64.urlsafe_b64decode(data + "==="[: len(data) % 4]).decode(errors="ignore"))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n".join(chunks)


def _gmail_service(token_path: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(Path(token_path).expanduser()))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _query(cfg: dict) -> str:
    gmail = cfg.get("capture", {}).get("gmail", {})
    senders = [f"from:{s}" for s in gmail.get("senders_allowlist", []) if s]
    subjects = [f'subject:"{s}"' for s in gmail.get("subject_patterns", []) if s]
    parts = []
    if senders:
        parts.append("(" + " OR ".join(senders) + ")")
    if subjects:
        parts.append("(" + " OR ".join(subjects) + ")")
    parts.append("newer_than:7d")
    return " ".join(parts)


def poll_once(cfg: dict, *, dry_run: bool = False) -> dict:
    gmail_cfg = cfg.get("capture", {}).get("gmail", {})
    token_path = gmail_cfg.get("token_path") or "~/.expense-bookkeeper/state/gmail_token.json"
    service = _gmail_service(token_path)
    seen_path = _state_path(cfg)
    seen = _load_seen(seen_path)
    listed = service.users().messages().list(userId="me", q=_query(cfg), maxResults=int(gmail_cfg.get("max_results", 25))).execute()
    added = 0
    skipped = 0
    errors: list[dict] = []
    for item in listed.get("messages", []) or []:
        msg_id = item["id"]
        if msg_id in seen:
            skipped += 1
            continue
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        text = _body_from_payload(msg.get("payload", {})) or msg.get("snippet", "")
        try:
            result = process_raw_event(text, cfg, source="gmail", dry_run=dry_run)
            added += int(result.get("appended") or 0)
            seen.add(msg_id)
        except Exception as exc:
            errors.append({"message_id": msg_id, "error": str(exc)})
    _save_seen(seen_path, seen)
    return {"added": added, "skipped": skipped, "errors": errors, "query": _query(cfg)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = poll_once(_load_config(args.config), dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"gmail_poller added={result['added']} skipped={result['skipped']} errors={len(result['errors'])}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
