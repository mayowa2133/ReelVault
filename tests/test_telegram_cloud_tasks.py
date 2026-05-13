import pytest
from fastapi import BackgroundTasks

from app.config import Settings
from app.models.schemas import ContentPillar, ProcessingStatus, ReelReference, SheetRow
from app.routes.telegram import schedule_reel_processing


class FakeTelegram:
    def __init__(self):
        self.messages = []

    async def send_message_async(self, chat_id: int, text: str):
        self.messages.append((chat_id, text))


class FakeSheets:
    def __init__(self, _settings):
        self.rows = {}
        self.appended = None
        self.updated = []

    def append_row(self, row: SheetRow) -> int:
        self.appended = row
        self.rows[10] = row
        return 10

    def get_row(self, row_index: int) -> SheetRow:
        return self.rows.get(row_index) or SheetRow(
            reel_url="https://www.instagram.com/reel/ABC123/",
            shortcode="ABC123",
            status=ProcessingStatus.PENDING_PILLAR_CONFIRMATION.value,
        )

    def update_row(self, row_index: int, row: SheetRow) -> None:
        self.rows[row_index] = row
        self.updated.append((row_index, row))


class FakeQueue:
    payloads = []

    def __init__(self, _settings):
        pass

    def enqueue_processing_task(self, payload):
        self.payloads.append(payload)
        return "task-name"


@pytest.mark.asyncio
async def test_cloud_tasks_backend_creates_row_and_enqueues(monkeypatch):
    fake_sheets = FakeSheets(None)
    FakeQueue.payloads = []
    monkeypatch.setattr("app.routes.telegram.GoogleSheetsService", lambda settings: fake_sheets)
    monkeypatch.setattr("app.routes.telegram.CloudTasksQueueService", FakeQueue)
    settings = Settings(
        processing_backend="cloud_tasks",
        gcp_project_id="project-123",
        task_request_secret="secret",
        cloud_tasks_target_url="https://example.run.app/tasks/process-reel",
    )

    queued = await schedule_reel_processing(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        settings=settings,
        background_tasks=BackgroundTasks(),
        telegram=FakeTelegram(),
        initial_pillar=ContentPillar.TECH,
        initial_pillar_source="telegram_exact",
    )

    assert queued is True
    assert fake_sheets.appended.status == ProcessingStatus.QUEUED.value
    assert fake_sheets.appended.pillar == "Tech"
    assert FakeQueue.payloads[0].row_index == 10
    assert FakeQueue.payloads[0].initial_pillar == ContentPillar.TECH


@pytest.mark.asyncio
async def test_cloud_tasks_backend_reuses_confirmed_row(monkeypatch):
    fake_sheets = FakeSheets(None)
    fake_sheets.rows[8] = SheetRow(
        reel_url="https://www.instagram.com/reel/ABC123/",
        shortcode="ABC123",
        status=ProcessingStatus.RECEIVED.value,
    )
    FakeQueue.payloads = []
    monkeypatch.setattr("app.routes.telegram.GoogleSheetsService", lambda settings: fake_sheets)
    monkeypatch.setattr("app.routes.telegram.CloudTasksQueueService", FakeQueue)
    settings = Settings(
        processing_backend="cloud_tasks",
        gcp_project_id="project-123",
        task_request_secret="secret",
        cloud_tasks_target_url="https://example.run.app/tasks/process-reel",
    )

    queued = await schedule_reel_processing(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        settings=settings,
        background_tasks=BackgroundTasks(),
        telegram=FakeTelegram(),
        initial_pillar=ContentPillar.MOTIVATION,
        initial_pillar_source="telegram_fuzzy_confirmed",
        existing_row_index=8,
    )

    assert queued is True
    assert fake_sheets.rows[8].status == ProcessingStatus.QUEUED.value
    assert fake_sheets.rows[8].pillar == "Motivation"
    assert FakeQueue.payloads[0].row_index == 8


@pytest.mark.asyncio
async def test_cloud_tasks_enqueue_failure_marks_row_failed(monkeypatch):
    class FailingQueue(FakeQueue):
        def enqueue_processing_task(self, payload):
            raise RuntimeError("queue unavailable")

    fake_sheets = FakeSheets(None)
    telegram = FakeTelegram()
    monkeypatch.setattr("app.routes.telegram.GoogleSheetsService", lambda settings: fake_sheets)
    monkeypatch.setattr("app.routes.telegram.CloudTasksQueueService", FailingQueue)
    settings = Settings(
        processing_backend="cloud_tasks",
        gcp_project_id="project-123",
        task_request_secret="secret",
        cloud_tasks_target_url="https://example.run.app/tasks/process-reel",
    )

    queued = await schedule_reel_processing(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        settings=settings,
        background_tasks=BackgroundTasks(),
        telegram=telegram,
    )

    assert queued is False
    assert fake_sheets.rows[10].status == ProcessingStatus.QUEUE_FAILED.value
    assert "queue unavailable" in fake_sheets.rows[10].error_message
    assert telegram.messages
