from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.models.schemas import ProcessingTaskPayload, ReelReference
from app.routes.tasks import router


def build_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_process_reel_task_rejects_missing_secret():
    client = build_client(Settings(task_request_secret="expected-secret"))
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        row_index=4,
    )

    response = client.post("/tasks/process-reel", json=payload.model_dump(mode="json"))

    assert response.status_code == 401


def test_process_reel_task_calls_workflow(monkeypatch):
    calls = []

    def fake_process(*args):
        calls.append(args)

    monkeypatch.setattr("app.routes.tasks.process_reel_inspiration", fake_process)

    settings = Settings(task_request_secret="expected-secret")
    client = build_client(settings)
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        row_index=4,
    )

    response = client.post(
        "/tasks/process-reel",
        json=payload.model_dump(mode="json"),
        headers={"X-ReelVault-Task-Secret": "expected-secret"},
    )

    assert response.status_code == 200
    assert response.json()["row_index"] == 4
    assert calls[0][0].shortcode == "ABC123"
    assert calls[0][1] == 123
    assert calls[0][5] == 4
