import json

from google.api_core.exceptions import AlreadyExists

from app.config import Settings
from app.models.schemas import ProcessingTaskPayload, ReelReference
from app.services.task_queue_service import (
    CLOUD_TASKS_TARGET_PATH,
    TASK_SECRET_HEADER,
    CloudTasksQueueService,
    cloud_task_id,
    is_uncertain_cloud_tasks_timeout,
)


class FakeTaskResponse:
    name = "projects/test/locations/us-central1/queues/reelvault-processing/tasks/task-1"


class FakeCloudTasksClient:
    def __init__(self):
        self.created_request = None
        self.timeout = None

    def queue_path(self, project: str, location: str, queue: str) -> str:
        return f"projects/{project}/locations/{location}/queues/{queue}"

    def create_task(self, request, timeout=None):
        self.created_request = request
        self.timeout = timeout
        return FakeTaskResponse()


def test_processing_task_payload_validates_required_fields():
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        row_index=4,
    )

    assert payload.reel.shortcode == "ABC123"
    assert payload.row_index == 4


def test_cloud_tasks_service_creates_expected_http_task():
    client = FakeCloudTasksClient()
    settings = Settings(
        gcp_project_id="project-123",
        gcp_location="us-central1",
        cloud_tasks_queue="reelvault-processing",
        cloud_tasks_target_url="https://example.run.app/tasks/process-reel",
        task_request_secret="task-secret",
        cloud_tasks_dispatch_deadline_seconds=1800,
    )
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        row_index=4,
    )

    task_name = CloudTasksQueueService(settings, client=client).enqueue_processing_task(payload)

    assert task_name.endswith("/task-1")
    request = client.created_request
    assert request["parent"] == "projects/project-123/locations/us-central1/queues/reelvault-processing"
    task = request["task"]
    assert task["name"].endswith("/tasks/reelvault-row-4-abc123")
    assert task["http_request"]["url"] == "https://example.run.app/tasks/process-reel"
    assert task["http_request"]["headers"][TASK_SECRET_HEADER] == "task-secret"
    assert json.loads(task["http_request"]["body"].decode("utf-8"))["row_index"] == 4
    assert task["dispatch_deadline"].seconds == 1800
    assert client.timeout == settings.cloud_tasks_create_timeout_seconds


def test_cloud_tasks_service_can_derive_target_url_from_base_url():
    client = FakeCloudTasksClient()
    settings = Settings(
        gcp_project_id="project-123",
        base_url="https://example.run.app/",
        task_request_secret="task-secret",
    )
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        row_index=4,
    )

    CloudTasksQueueService(settings, client=client).enqueue_processing_task(payload)

    assert client.created_request["task"]["http_request"]["url"] == f"https://example.run.app{CLOUD_TASKS_TARGET_PATH}"


def test_cloud_tasks_service_treats_existing_deterministic_task_as_success():
    class ExistingTaskClient(FakeCloudTasksClient):
        def create_task(self, request, timeout=None):
            self.created_request = request
            self.timeout = timeout
            raise AlreadyExists("Task already exists")

    client = ExistingTaskClient()
    settings = Settings(
        gcp_project_id="project-123",
        gcp_location="us-central1",
        cloud_tasks_queue="reelvault-processing",
        cloud_tasks_target_url="https://example.run.app/tasks/process-reel",
        task_request_secret="task-secret",
    )
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123"),
        chat_id=123,
        row_index=4,
    )

    task_name = CloudTasksQueueService(settings, client=client).enqueue_processing_task(payload)

    assert task_name == client.created_request["task"]["name"]
    assert task_name.endswith("/tasks/reelvault-row-4-abc123")


def test_cloud_task_id_sanitizes_shortcode():
    payload = ProcessingTaskPayload(
        reel=ReelReference(url="https://www.instagram.com/reel/ABC 123!/", shortcode="ABC 123!"),
        chat_id=123,
        row_index=4,
    )

    assert cloud_task_id(payload) == "reelvault-row-4-abc-123"


def test_uncertain_cloud_tasks_timeout_detection():
    assert is_uncertain_cloud_tasks_timeout(TimeoutError("The read operation timed out"))
    assert is_uncertain_cloud_tasks_timeout(RuntimeError("deadline exceeded while creating task"))
    assert not is_uncertain_cloud_tasks_timeout(RuntimeError("permission denied"))
