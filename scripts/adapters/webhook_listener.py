#!/usr/bin/env python3
"""Small local HTTP receiver for Android/Tasker or hosted webhook capture."""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

THIS = Path(__file__).resolve()
SCRIPTS = THIS.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capture_pipeline import process_raw_event  # noqa: E402


def _load_config(path: str | Path) -> dict:
    with Path(path).expanduser().open() as f:
        return yaml.safe_load(f) or {}


class Handler(BaseHTTPRequestHandler):
    config: dict = {}
    dry_run: bool = False

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/expense-bookkeeper/capture":
            self._json(404, {"ok": False, "error": "unknown endpoint"})
            return
        expected = self.config.get("capture", {}).get("shared_secret", "")
        if expected and self.headers.get("X-Expense-Bookkeeper-Secret") != expected:
            self._json(401, {"ok": False, "error": "bad secret"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            data = json.loads(self.rfile.read(length).decode() or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return
        raw = (data.get("raw") or data.get("text") or "").strip()
        if not raw:
            self._json(400, {"ok": False, "error": "missing raw"})
            return
        try:
            result = process_raw_event(raw, self.config, source=data.get("source") or "webhook", dry_run=self.dry_run)
        except Exception as exc:
            self._json(500, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "status": result["transaction"]["status"], "merchant": result["transaction"]["merchant_raw"]})

    def log_message(self, fmt, *args):
        if self.config.get("capture", {}).get("log_http", False):
            super().log_message(fmt, *args)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    Handler.config = _load_config(args.config)
    Handler.dry_run = args.dry_run
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"expense-bookkeeper webhook listening on http://{args.host}:{args.port}/expense-bookkeeper/capture")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
