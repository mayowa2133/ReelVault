from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.models.schemas import DownloadResult
from app.routes.diagnostics import router


def build_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_download_diagnostic_rejects_missing_secret(tmp_path):
    client = build_client(Settings(task_request_secret="expected-secret", temp_dir=tmp_path))

    response = client.post("/diagnostics/download", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"})

    assert response.status_code == 401


def test_download_diagnostic_rejects_unsupported_url(tmp_path):
    client = build_client(Settings(task_request_secret="expected-secret", temp_dir=tmp_path))

    response = client.post(
        "/diagnostics/download",
        json={"url": "https://example.com/video"},
        headers={"X-ReelVault-Task-Secret": "expected-secret"},
    )

    assert response.status_code == 400


def test_download_diagnostic_calls_downloader(tmp_path, monkeypatch):
    output_file = tmp_path / "video.mp4"

    class FakeDownloader:
        def __init__(self, settings, yt_dlp_debug_log=None):
            self.settings = settings
            self.yt_dlp_debug_log = yt_dlp_debug_log

        def download(self, url: str, output_dir: Path) -> DownloadResult:
            if self.yt_dlp_debug_log is not None:
                self.yt_dlp_debug_log.append("debug line")
            output_file.write_bytes(b"video")
            return DownloadResult(
                success=True,
                status="download_complete",
                file_path=output_file,
                title="Me at the zoo",
                creator_username="jawed",
                metadata={"id": "jNQXAC9IVRw"},
            )

    monkeypatch.setattr("app.routes.diagnostics.DownloaderService", FakeDownloader)
    client = build_client(Settings(task_request_secret="expected-secret", temp_dir=tmp_path))

    response = client.post(
        "/diagnostics/download",
        json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"},
        headers={"X-ReelVault-Task-Secret": "expected-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "youtube"
    assert body["status"] == "download_complete"
    assert body["title"] == "Me at the zoo"
    assert body["file_size_bytes"] == 5
    assert body["downloader"]["yt_dlp_available"] is True
    assert "yt_dlp_debug_log" not in body


def test_download_diagnostic_can_include_debug_log(tmp_path, monkeypatch):
    class FakeDownloader:
        def __init__(self, settings, yt_dlp_debug_log=None):
            self.settings = settings
            self.yt_dlp_debug_log = yt_dlp_debug_log

        def download(self, url: str, output_dir: Path) -> DownloadResult:
            if self.yt_dlp_debug_log is not None:
                self.yt_dlp_debug_log.append("debug: generated po_token=[REDACTED]")
            return DownloadResult(success=False, status="download_failed", error_message="blocked")

    monkeypatch.setattr("app.routes.diagnostics.DownloaderService", FakeDownloader)
    client = build_client(Settings(task_request_secret="expected-secret", temp_dir=tmp_path))

    response = client.post(
        "/diagnostics/download",
        json={
            "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            "include_debug_log": True,
            "debug_log_max_chars": 1000,
        },
        headers={"X-ReelVault-Task-Secret": "expected-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["yt_dlp_debug_log"] == "debug: generated po_token=[REDACTED]"


def test_download_diagnostic_returns_failed_result(tmp_path, monkeypatch):
    class FakeDownloader:
        def __init__(self, settings, yt_dlp_debug_log=None):
            self.settings = settings

        def download(self, url: str, output_dir: Path) -> DownloadResult:
            return DownloadResult(
                success=False,
                status="download_failed",
                error_message="blocked",
            )

    monkeypatch.setattr("app.routes.diagnostics.DownloaderService", FakeDownloader)
    client = build_client(Settings(task_request_secret="expected-secret", temp_dir=tmp_path))

    response = client.post(
        "/diagnostics/download",
        json={"url": "https://www.instagram.com/reel/DWuZeLziciR/"},
        headers={"X-ReelVault-Task-Secret": "expected-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["provider"] == "instagram"
    assert body["status"] == "download_failed"
    assert body["error"] == "blocked"
