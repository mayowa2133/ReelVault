from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.config import Settings
from app.utils.errors import ExternalServiceError


GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

GOOGLE_API_SCOPES = [
    GOOGLE_DRIVE_SCOPE,
    GOOGLE_DOCS_SCOPE,
    GOOGLE_SHEETS_SCOPE,
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GoogleOAuthCredentialsProvider:
    """Load, validate, and refresh user OAuth credentials for Google APIs."""

    def __init__(self, settings: Settings, scopes: list[str] | None = None):
        self.settings = settings
        self.scopes = scopes or GOOGLE_API_SCOPES

    def get_credentials(self) -> Credentials:
        token_info, token_file = self._load_token_info()

        declared_scopes = read_declared_token_info_scopes(token_info)
        missing_scopes = [scope for scope in self.scopes if scope not in declared_scopes]
        if missing_scopes:
            missing = ", ".join(missing_scopes)
            raise ExternalServiceError(
                "Google OAuth token is missing required scopes. "
                f"Missing: {missing}. "
                "Delete token.json and run `python scripts/google_oauth_setup.py` again.",
                step="google_oauth",
            )

        credentials = Credentials.from_authorized_user_info(token_info, self.scopes)
        if not credentials.has_scopes(self.scopes):
            raise ExternalServiceError(
                "Google OAuth token does not include the required scopes for this Google API call. "
                "Delete token.json and run `python scripts/google_oauth_setup.py` again.",
                step="google_oauth",
            )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_credentials_if_possible(credentials, token_file)

        if not credentials.valid:
            raise ExternalServiceError(
                "Google OAuth token is invalid or expired without a refresh token. "
                "Run `python scripts/google_oauth_setup.py` again.",
                step="google_oauth",
            )

        return credentials

    def _load_token_info(self) -> tuple[dict, Path | None]:
        if self.settings.google_oauth_token_json:
            try:
                parsed = json.loads(self.settings.google_oauth_token_json)
            except json.JSONDecodeError as exc:
                raise ExternalServiceError(
                    "GOOGLE_OAUTH_TOKEN_JSON is not valid JSON",
                    step="google_oauth",
                ) from exc
            if not isinstance(parsed, dict):
                raise ExternalServiceError("GOOGLE_OAUTH_TOKEN_JSON must contain a JSON object", step="google_oauth")
            return parsed, None

        token_file = self._token_file()
        if not token_file.exists():
            raise ExternalServiceError(
                f"Google OAuth token file not found at {token_file}. "
                "Run `python scripts/google_oauth_setup.py` to create token.json.",
                step="google_oauth",
            )
        try:
            parsed = json.loads(token_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                f"Google OAuth token file is not valid JSON: {token_file}",
                step="google_oauth",
            ) from exc
        if not isinstance(parsed, dict):
            raise ExternalServiceError(f"Google OAuth token file must contain a JSON object: {token_file}", step="google_oauth")
        return parsed, token_file

    def _token_file(self) -> Path:
        if not self.settings.google_oauth_token_file:
            raise ExternalServiceError("GOOGLE_OAUTH_TOKEN_FILE is not configured", step="google_oauth")
        return resolve_configured_secret_path(self.settings.google_oauth_token_file)

    def _save_credentials_if_possible(self, credentials: Credentials, token_file: Path | None) -> None:
        if token_file is None:
            return
        token_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            token_file.write_text(credentials.to_json(), encoding="utf-8")
        except OSError:
            return


def resolve_configured_secret_path(configured_path: str) -> Path:
    path = Path(configured_path)
    if path.exists():
        return path

    if path.is_absolute() and len(path.parts) >= 3 and path.parts[1] == "secrets":
        local_path = PROJECT_ROOT / "secrets" / Path(*path.parts[2:])
        if local_path.exists() or local_path.parent.exists():
            return local_path

    return path


def read_declared_token_scopes(token_file: Path) -> set[str]:
    """Return the scopes Google actually stored in token.json."""
    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalServiceError(
            f"Google OAuth token file is not valid JSON: {token_file}",
            step="google_oauth",
        ) from exc

    if not isinstance(data, dict):
        return set()
    return read_declared_token_info_scopes(data)


def read_declared_token_info_scopes(data: dict) -> set[str]:
    """Return the scopes Google actually stored in authorized-user token data."""
    raw_scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(raw_scopes, str):
        return {scope for scope in raw_scopes.split() if scope}
    if isinstance(raw_scopes, list):
        return {str(scope) for scope in raw_scopes if scope}
    return set()
