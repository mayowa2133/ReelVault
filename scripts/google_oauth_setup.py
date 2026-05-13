#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.services.google_oauth_service import GOOGLE_API_SCOPES, resolve_configured_secret_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Google OAuth consent and create token.json for ReelVault Drive, Docs, and Sheets access."
    )
    parser.add_argument(
        "--credentials",
        help="Path to Google OAuth client credentials.json. Defaults to GOOGLE_OAUTH_CLIENT_SECRET_FILE.",
    )
    parser.add_argument(
        "--token",
        help="Path to write token.json. Defaults to GOOGLE_OAUTH_TOKEN_FILE.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local callback port. Use 0 to choose a free port.",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    settings = Settings()

    credentials_file = resolve_configured_secret_path(
        args.credentials or settings.google_oauth_client_secret_file or "/secrets/credentials.json"
    )
    token_file = resolve_configured_secret_path(args.token or settings.google_oauth_token_file or "/secrets/token.json")

    if not credentials_file.exists():
        raise SystemExit(
            f"OAuth client credentials file not found: {credentials_file}\n"
            "Download it from Google Cloud and save it as secrets/credentials.json."
        )

    token_file.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), GOOGLE_API_SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=args.port,
        open_browser=True,
        authorization_prompt_message="Opening browser for Google OAuth consent: {url}",
        success_message="Google OAuth setup complete. You can close this browser tab.",
        access_type="offline",
        prompt="consent",
    )

    token_file.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Created Google OAuth token: {token_file}")
    print("Authorized scopes:")
    for scope in GOOGLE_API_SCOPES:
        print(f"- {scope}")


if __name__ == "__main__":
    main()
