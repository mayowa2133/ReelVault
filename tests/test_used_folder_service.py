from dataclasses import dataclass

from app.config import Settings
from app.models.schemas import SheetUsedWebhookPayload
from app.services.used_folder_service import UsedFolderService


@dataclass(frozen=True)
class FakeFolder:
    folder_id: str
    name: str
    web_view_link: str


class FakeDrive:
    def __init__(self):
        self.used_moves = []
        self.active_moves = []

    def move_inspiration_folder_to_used(self, folder_id: str, pillar: str):
        self.used_moves.append((folder_id, pillar))
        return FakeFolder(folder_id="used-folder", name="Used", web_view_link="https://drive.google.com/drive/folders/used-folder")

    def move_inspiration_folder_to_pillar(self, folder_id: str, pillar: str):
        self.active_moves.append((folder_id, pillar))
        return "pillar-folder"


class FakeSheets:
    def __init__(self):
        self.update_calls = []
        self.sync_calls = []
        self.sort_calls = []

    def update_used_state(self, *args, **kwargs):
        self.update_calls.append((args, kwargs))

    def sync_used_value(self, **kwargs):
        self.sync_calls.append(kwargs)
        return 2

    def sort_tabs_for_usage(self, pillar):
        self.sort_calls.append(pillar)
        return {"Reels": True, pillar: True}


def test_used_folder_service_moves_checked_row_to_pillar_used_folder():
    drive = FakeDrive()
    sheets = FakeSheets()
    payload = SheetUsedWebhookPayload(
        sheetName="Reels",
        rowNumber=2,
        used=True,
        pillar="Motivation",
        shortcode="ABC123",
        reelUrl="https://www.instagram.com/reel/ABC123/",
        inspirationFolderLink="https://drive.google.com/drive/folders/folder-id",
    )

    result = UsedFolderService(Settings(), drive=drive, sheets=sheets).handle_used_change(payload)

    assert result.moved is True
    assert result.synced_rows == 2
    assert drive.used_moves == [("folder-id", "Motivation")]
    assert drive.active_moves == []
    assert sheets.update_calls[0][0][:3] == ("Reels", 2, True)
    assert sheets.update_calls[0][1]["used_at"]
    assert sheets.sync_calls[0]["used"] is True
    assert sheets.sync_calls[0]["used_at"] == sheets.update_calls[0][1]["used_at"]
    assert sheets.sort_calls == ["Motivation"]


def test_used_folder_service_moves_unchecked_row_back_to_pillar_folder():
    drive = FakeDrive()
    sheets = FakeSheets()
    payload = SheetUsedWebhookPayload(
        sheetName="Motivation",
        rowNumber=5,
        used=False,
        pillar="Motivation",
        inspirationFolderLink="folder-id",
    )

    result = UsedFolderService(Settings(), drive=drive, sheets=sheets).handle_used_change(payload)

    assert result.moved is True
    assert drive.active_moves == [("folder-id", "Motivation")]
    assert drive.used_moves == []
    assert sheets.update_calls[0][0][:3] == ("Motivation", 5, False)
    assert sheets.update_calls[0][1]["used_at"] == ""
    assert sheets.sync_calls[0]["edited_tab_name"] == "Motivation"
    assert sheets.sync_calls[0]["edited_row_number"] == 5


def test_used_folder_service_ignores_missing_folder_link_but_syncs_sheet():
    drive = FakeDrive()
    sheets = FakeSheets()
    payload = SheetUsedWebhookPayload(sheetName="Reels", rowNumber=2, used=True, pillar="Motivation")

    result = UsedFolderService(Settings(), drive=drive, sheets=sheets).handle_used_change(payload)

    assert result.moved is False
    assert result.message == "Skipped Drive move because the row has no Inspiration Folder Link."
    assert drive.used_moves == []
    assert sheets.update_calls
    assert sheets.sync_calls
