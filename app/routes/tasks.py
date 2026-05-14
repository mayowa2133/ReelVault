from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.models.schemas import ProcessingTaskPayload
from app.services.task_queue_service import TASK_SECRET_HEADER
from app.services.workflow_service import process_reel_inspiration

router = APIRouter(tags=["tasks"])


@router.post("/tasks/process-reel")
def process_reel_task(
    payload: ProcessingTaskPayload,
    x_reelvault_task_secret: str | None = Header(default=None, alias=TASK_SECRET_HEADER),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | int | str]:
    if not settings.task_request_secret:
        raise HTTPException(status_code=500, detail="TASK_REQUEST_SECRET is not configured")
    if x_reelvault_task_secret != settings.task_request_secret:
        raise HTTPException(status_code=401, detail="Invalid task secret")

    process_reel_inspiration(
        payload.reel,
        payload.chat_id,
        settings,
        payload.initial_pillar,
        payload.initial_pillar_source,
        payload.row_index,
        payload.telegram_media,
    )
    return {"ok": True, "row_index": payload.row_index, "message": "Processed"}
