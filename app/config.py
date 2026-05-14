from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_allowed_user_id: int | None = None
    telegram_webhook_secret: str | None = None
    base_url: str | None = None
    processing_backend: Literal["background", "cloud_tasks"] = "background"

    openai_api_key: str = ""
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_analysis_model: str = "gpt-4.1-mini"

    google_oauth_client_secret_file: str | None = "/secrets/credentials.json"
    google_oauth_token_file: str | None = "/secrets/token.json"
    google_oauth_token_json: str | None = None
    google_drive_folder_id: str | None = None
    google_sheet_id: str | None = None
    google_sheet_tab_name: str = "Reels"

    gcp_project_id: str | None = None
    gcp_location: str = "us-central1"
    cloud_tasks_queue: str = "reelvault-processing"
    cloud_tasks_target_url: str | None = None
    task_request_secret: str | None = None
    cloud_tasks_dispatch_deadline_seconds: int = 1800
    cloud_tasks_create_timeout_seconds: int = 30

    temp_dir: Path = Field(default=Path("/tmp/reelvault"))
    max_video_size_mb: int = 100
    max_audio_size_mb: int = 24
    enable_video_download: bool = True
    enable_audio_upload: bool = True
    enable_debug_logging: bool = False

    request_timeout_seconds: int = 30

    @field_validator(
        "telegram_allowed_user_id",
        "telegram_webhook_secret",
        "base_url",
        "google_oauth_client_secret_file",
        "google_oauth_token_file",
        "google_oauth_token_json",
        "google_drive_folder_id",
        "google_sheet_id",
        "gcp_project_id",
        "cloud_tasks_target_url",
        "task_request_secret",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("temp_dir", mode="before")
    @classmethod
    def parse_temp_dir(cls, value: Any) -> Path:
        return Path(value or "/tmp/reelvault")

    @field_validator("google_sheet_id", mode="before")
    @classmethod
    def normalize_google_sheet_id(cls, value: Any) -> Any:
        if not value:
            return value
        return extract_google_sheet_id(str(value).strip())

    @field_validator("google_drive_folder_id", mode="before")
    @classmethod
    def normalize_google_drive_folder_id(cls, value: Any) -> Any:
        if not value:
            return value
        return extract_google_drive_folder_id(str(value).strip())

    @property
    def google_sheet_url(self) -> str | None:
        if not self.google_sheet_id:
            return None
        return f"https://docs.google.com/spreadsheets/d/{self.google_sheet_id}/edit"


def extract_google_sheet_id(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path if parsed.scheme and parsed.netloc else value

    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", path)
    if match:
        return match.group(1)

    if "/edit" in value:
        return value.split("/edit", 1)[0].rstrip("/").split("/")[-1]

    return value.strip().strip("/")


def extract_google_drive_folder_id(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        query_id = parse_qs(parsed.query).get("id")
        if query_id and query_id[0]:
            return query_id[0]

        match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
        if match:
            return match.group(1)

    if "/folders/" in value:
        return value.split("/folders/", 1)[1].split("?", 1)[0].split("/", 1)[0]

    return value.strip().strip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
