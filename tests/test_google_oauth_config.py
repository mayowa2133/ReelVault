import json

from app.config import Settings
from app.services.google_oauth_service import (
    GOOGLE_API_SCOPES,
    GOOGLE_DRIVE_SCOPE,
    GoogleOAuthCredentialsProvider,
    read_declared_token_scopes,
)


def test_env_example_uses_google_oauth_files():
    settings = Settings(_env_file=".env.example")

    assert settings.google_oauth_client_secret_file == "/secrets/credentials.json"
    assert settings.google_oauth_token_file == "/secrets/token.json"
    assert "google_oauth_client_secret_file" in Settings.model_fields
    assert "google_oauth_token_file" in Settings.model_fields


def test_google_oauth_scopes_cover_drive_docs_and_sheets():
    assert "https://www.googleapis.com/auth/drive" in GOOGLE_API_SCOPES
    assert "https://www.googleapis.com/auth/documents" in GOOGLE_API_SCOPES
    assert "https://www.googleapis.com/auth/spreadsheets" in GOOGLE_API_SCOPES


def test_read_declared_token_scopes_from_list(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"scopes": [GOOGLE_DRIVE_SCOPE]}), encoding="utf-8")

    assert read_declared_token_scopes(token_file) == {GOOGLE_DRIVE_SCOPE}


def test_read_declared_token_scopes_from_space_separated_scope(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text(
        json.dumps({"scope": f"{GOOGLE_DRIVE_SCOPE} https://www.googleapis.com/auth/spreadsheets"}),
        encoding="utf-8",
    )

    assert GOOGLE_DRIVE_SCOPE in read_declared_token_scopes(token_file)


def test_google_oauth_provider_loads_token_json_from_environment():
    token_info = {
        "token": "ya29.fake-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "client-secret",
        "scopes": [GOOGLE_DRIVE_SCOPE],
        "expiry": "2999-01-01T00:00:00Z",
    }
    settings = Settings(
        google_oauth_token_json=json.dumps(token_info),
        google_oauth_token_file=None,
    )

    credentials = GoogleOAuthCredentialsProvider(settings, scopes=[GOOGLE_DRIVE_SCOPE]).get_credentials()

    assert credentials.token == "ya29.fake-token"
    assert credentials.has_scopes([GOOGLE_DRIVE_SCOPE])


def test_google_oauth_refresh_without_file_does_not_attempt_persistence(monkeypatch):
    token_info = {
        "token": "expired-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "client-secret",
        "scopes": [GOOGLE_DRIVE_SCOPE],
        "expiry": "2000-01-01T00:00:00Z",
    }
    settings = Settings(
        google_oauth_token_json=json.dumps(token_info),
        google_oauth_token_file=None,
    )

    def fake_refresh(self, request):
        self.token = "refreshed-token"
        self.expiry = None

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", fake_refresh)

    credentials = GoogleOAuthCredentialsProvider(settings, scopes=[GOOGLE_DRIVE_SCOPE]).get_credentials()

    assert credentials.token == "refreshed-token"
