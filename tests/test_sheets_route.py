from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.routes.sheets import router


def build_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@dataclass(frozen=True)
class FakeResult:
    moved: bool = True
    target: str = "target"
    folder_id: str = "folder-id"
    synced_rows: int = 1
    message: str = "ok"


def valid_payload():
    return {
        "sheetName": "Reels",
        "rowNumber": 2,
        "used": True,
        "pillar": "Motivation",
        "shortcode": "ABC123",
        "reelUrl": "https://www.instagram.com/reel/ABC123/",
        "inspirationFolderLink": "https://drive.google.com/drive/folders/folder-id",
    }


def test_sheets_used_webhook_rejects_missing_secret():
    client = build_client(Settings(sheets_webhook_secret="expected-secret"))

    response = client.post("/webhook/sheets/used", json=valid_payload())

    assert response.status_code == 401


def test_sheets_used_webhook_rejects_unconfigured_secret():
    client = build_client(Settings())

    response = client.post(
        "/webhook/sheets/used",
        json=valid_payload(),
        headers={"X-ReelVault-Sheets-Secret": "expected-secret"},
    )

    assert response.status_code == 500


def test_sheets_used_webhook_calls_service(monkeypatch):
    calls = []

    class FakeService:
        def __init__(self, settings):
            self.settings = settings

        def handle_used_change(self, payload):
            calls.append(payload)
            return FakeResult()

    monkeypatch.setattr("app.routes.sheets.UsedFolderService", FakeService)
    client = build_client(Settings(sheets_webhook_secret="expected-secret"))

    response = client.post(
        "/webhook/sheets/used",
        json=valid_payload(),
        headers={"X-ReelVault-Sheets-Secret": "expected-secret"},
    )

    assert response.status_code == 200
    assert response.json()["moved"] is True
    assert calls[0].shortcode == "ABC123"
