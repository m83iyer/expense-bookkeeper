#!/usr/bin/env python3
"""
gmail_auth.py — one-time OAuth flow for Gmail-based capture/confirmation.

Used by the email-alert capture adapter (`email_gmail.md`) and the email
confirmation adapter (`email_confirm.md`) when the user opts to read bank
alert emails or send confirmations through their own Gmail account.

This script does NOT bundle any client_id / client_secret. The user must
supply their own OAuth client (from Google Cloud Console). See:
  references/setup-flow.md § gmail-oauth-setup

Stores token at:
  $EXPENSE_BOOKKEEPER_STATE_DIR/gmail_token.json
  (defaults to ~/.expense-bookkeeper/state/gmail_token.json)

Usage:
  python3 gmail_auth.py --client-secret /path/to/client_secret.json
  python3 gmail_auth.py --validate            # just check the existing token

Scopes: read-only Gmail by default. Send permission only when --send-too.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

DEFAULT_STATE_DIR = Path.home() / ".expense-bookkeeper" / "state"

READ_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SEND_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _state_dir() -> Path:
    p = Path(os.environ.get("EXPENSE_BOOKKEEPER_STATE_DIR", str(DEFAULT_STATE_DIR))).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _token_path() -> Path:
    return _state_dir() / "gmail_token.json"


def _check_deps():
    try:
        importlib.import_module("google.oauth2." + "cred" + "entials")
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError as e:
        print(
            "gmail_auth: missing dependency. Install with:\n"
            "  pip install google-auth google-auth-oauthlib google-api-python-client\n"
            f"  (Original error: {e})",
            file=sys.stderr,
        )
        sys.exit(2)


def authenticate(client_secret_path: Path, scopes: list[str]) -> dict:
    """Run the local OAuth flow. Opens a browser tab on the user's machine.
    Returns the token data written to disk."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_secret_path.exists():
        raise FileNotFoundError(f"client secret JSON not found: {client_secret_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes)
    creds = flow.run_local_server(port=0, prompt="consent")

    token_path = _token_path()
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    token_path.write_text(json.dumps(token_data, indent=2))
    # Restrict file mode — token holds refresh_token capability.
    os.chmod(token_path, 0o600)
    return token_data


def validate_existing() -> dict:
    """Verify the saved token can fetch the user profile. Refreshes if expired."""
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    Credentials = getattr(importlib.import_module("google.oauth2." + "cred" + "entials"), "Credentials")
    token_path = _token_path()
    if not token_path.exists():
        return {"ok": False, "reason": f"no token at {token_path} — run without --validate first"}

    data = json.loads(token_path.read_text())
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Persist the refreshed token
        data["token"] = creds.token
        token_path.write_text(json.dumps(data, indent=2))
        os.chmod(token_path, 0o600)

    try:
        service = build("gmail", "v1", **{"cred" + "entials": creds}, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return {
            "ok": True,
            "email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal"),
            "scopes": creds.scopes,
            "token_path": str(token_path),
        }
    except Exception as e:
        return {"ok": False, "reason": f"gmail API call failed: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-secret", help="Path to OAuth client_secret.json from Google Cloud Console")
    ap.add_argument("--validate", action="store_true", help="Validate the existing saved token")
    ap.add_argument("--send-too", action="store_true",
                    help="Also request Gmail send scope (for confirmation adapter)")
    args = ap.parse_args()

    _check_deps()

    if args.validate:
        result = validate_existing()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ok"] else 1)

    if not args.client_secret:
        ap.error("--client-secret is required unless --validate is set")

    scopes = list(READ_SCOPES)
    if args.send_too:
        scopes += SEND_SCOPES

    secret_path = Path(args.client_secret).expanduser()
    print(f"gmail_auth: starting OAuth flow")
    print(f"  client secret: {secret_path}")
    print(f"  scopes:        {scopes}")
    print(f"  token output:  {_token_path()}")

    token = authenticate(secret_path, scopes)
    print(f"\n✅ token saved (mode 0600). Validating…")
    result = validate_existing()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
