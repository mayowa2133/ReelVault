from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.models.schemas import SheetUsedWebhookPayload
from app.services.used_folder_service import UsedFolderService

SHEETS_SECRET_HEADER = "X-ReelVault-Sheets-Secret"

router = APIRouter(tags=["sheets"])


@router.post("/webhook/sheets/used")
def sheets_used_webhook(
    payload: SheetUsedWebhookPayload,
    x_reelvault_sheets_secret: str | None = Header(default=None, alias=SHEETS_SECRET_HEADER),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | int | str | None]:
    if not settings.sheets_webhook_secret:
        raise HTTPException(status_code=500, detail="SHEETS_WEBHOOK_SECRET is not configured")
    if x_reelvault_sheets_secret != settings.sheets_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid Sheets webhook secret")

    result = UsedFolderService(settings).handle_used_change(payload)
    return {
        "ok": True,
        "moved": result.moved,
        "target": result.target,
        "folder_id": result.folder_id,
        "synced_rows": result.synced_rows,
        "message": result.message,
    }
