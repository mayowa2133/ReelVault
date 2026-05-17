from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.models.schemas import SheetUsedWebhookPayload, utc_now_iso
from app.services.google_drive_service import GoogleDriveService, extract_drive_folder_id_from_link
from app.services.google_sheets_service import GoogleSheetsService
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class UsedFolderResult:
    moved: bool
    target: str
    folder_id: str | None
    synced_rows: int
    message: str


class UsedFolderService:
    """Move inspiration folders when the Google Sheets Used checkbox changes."""

    def __init__(
        self,
        settings: Settings,
        drive: GoogleDriveService | None = None,
        sheets: GoogleSheetsService | None = None,
    ):
        self.settings = settings
        self.drive = drive or GoogleDriveService(settings)
        self.sheets = sheets or GoogleSheetsService(settings)

    def handle_used_change(self, payload: SheetUsedWebhookPayload) -> UsedFolderResult:
        folder_id = extract_drive_folder_id_from_link(payload.inspiration_folder_link)
        used_at = (payload.used_at or utc_now_iso()) if payload.used else ""

        if folder_id and payload.pillar:
            if payload.used:
                used_folder = self.drive.move_inspiration_folder_to_used(folder_id, payload.pillar)
                target = used_folder.web_view_link
                message = "Moved inspiration folder to Used."
            else:
                target_folder_id = self.drive.move_inspiration_folder_to_pillar(folder_id, payload.pillar)
                target = target_folder_id
                message = "Moved inspiration folder back to active pillar folder."
            moved = True
        elif folder_id:
            logger.warning(
                "used_folder_move_skipped_missing_pillar",
                extra={"folder_id": folder_id, "row_number": payload.row_number, "sheet_name": payload.sheet_name},
            )
            target = ""
            message = "Skipped Drive move because the row has no Pillar."
            moved = False
        else:
            target = ""
            message = "Skipped Drive move because the row has no Inspiration Folder Link."
            moved = False

        self.sheets.update_used_state(payload.sheet_name, payload.row_number, payload.used, used_at=used_at)
        synced_rows = self.sheets.sync_used_value(
            used=payload.used,
            pillar=payload.pillar,
            inspiration_folder_link=payload.inspiration_folder_link,
            shortcode=payload.shortcode,
            reel_url=payload.reel_url,
            edited_tab_name=payload.sheet_name,
            edited_row_number=payload.row_number,
            used_at=used_at,
        )
        self.sheets.sort_tabs_for_usage(payload.pillar)

        return UsedFolderResult(
            moved=moved,
            target=target,
            folder_id=folder_id,
            synced_rows=synced_rows,
            message=message,
        )
