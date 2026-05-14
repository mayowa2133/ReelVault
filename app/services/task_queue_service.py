from __future__ import annotations

import re

from google.api_core.exceptions import AlreadyExists, DeadlineExceeded
from google.cloud import tasks_v2
from google.protobuf import duration_pb2

from app.config import Settings
from app.models.schemas import ProcessingTaskPayload
from app.utils.errors import ExternalServiceError


TASK_SECRET_HEADER = "X-ReelVault-Task-Secret"
CLOUD_TASKS_TARGET_PATH = "/tasks/process-reel"


class CloudTasksQueueService:
    """Create Cloud Tasks that call the ReelVault processing endpoint."""

    def __init__(self, settings: Settings, client: tasks_v2.CloudTasksClient | None = None):
        self.settings = settings
        self.client = client or tasks_v2.CloudTasksClient()

    def enqueue_processing_task(self, payload: ProcessingTaskPayload) -> str:
        parent = self._queue_path()
        target_url = self._target_url()
        task_secret = self._task_secret()

        dispatch_deadline = duration_pb2.Duration()
        dispatch_deadline.FromSeconds(self.settings.cloud_tasks_dispatch_deadline_seconds)

        task = {
            "name": cloud_task_name(parent, payload),
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": target_url,
                "headers": {
                    "Content-Type": "application/json",
                    TASK_SECRET_HEADER: task_secret,
                },
                "body": payload.model_dump_json().encode("utf-8"),
            },
            "dispatch_deadline": dispatch_deadline,
        }
        try:
            response = self.client.create_task(
                request={"parent": parent, "task": task},
                timeout=self.settings.cloud_tasks_create_timeout_seconds,
            )
        except AlreadyExists:
            return task["name"]
        return response.name

    def _queue_path(self) -> str:
        if not self.settings.gcp_project_id:
            raise ExternalServiceError("GCP_PROJECT_ID is required for Cloud Tasks", step="cloud_tasks")
        if not self.settings.gcp_location:
            raise ExternalServiceError("GCP_LOCATION is required for Cloud Tasks", step="cloud_tasks")
        if not self.settings.cloud_tasks_queue:
            raise ExternalServiceError("CLOUD_TASKS_QUEUE is required for Cloud Tasks", step="cloud_tasks")
        return self.client.queue_path(
            self.settings.gcp_project_id,
            self.settings.gcp_location,
            self.settings.cloud_tasks_queue,
        )

    def _target_url(self) -> str:
        if self.settings.cloud_tasks_target_url:
            return self.settings.cloud_tasks_target_url
        if self.settings.base_url:
            return self.settings.base_url.rstrip("/") + CLOUD_TASKS_TARGET_PATH
        raise ExternalServiceError(
            "CLOUD_TASKS_TARGET_URL or BASE_URL is required for Cloud Tasks",
            step="cloud_tasks",
        )

    def _task_secret(self) -> str:
        if not self.settings.task_request_secret:
            raise ExternalServiceError("TASK_REQUEST_SECRET is required for Cloud Tasks", step="cloud_tasks")
        return self.settings.task_request_secret


def cloud_task_name(parent: str, payload: ProcessingTaskPayload) -> str:
    return f"{parent}/tasks/{cloud_task_id(payload)}"


def cloud_task_id(payload: ProcessingTaskPayload) -> str:
    shortcode = payload.reel.shortcode or "reel"
    safe_shortcode = re.sub(r"[^A-Za-z0-9_-]+", "-", shortcode).strip("-")[:64] or "reel"
    return f"reelvault-row-{payload.row_index}-{safe_shortcode}".lower()


def is_uncertain_cloud_tasks_timeout(exc: Exception) -> bool:
    if isinstance(exc, (DeadlineExceeded, TimeoutError)):
        return True

    message = str(exc).lower()
    timeout_fragments = (
        "deadline exceeded",
        "read operation timed out",
        "timed out",
        "timeout",
    )
    return any(fragment in message for fragment in timeout_fragments)
