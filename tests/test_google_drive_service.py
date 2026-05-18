from app.config import Settings
from app.models.schemas import ContentPillar
from app.services.google_drive_service import (
    DriveFolderResult,
    GoogleDriveService,
    escape_drive_query_value,
    extract_drive_folder_id_from_link,
    inspiration_folder_name,
    pillar_folder_name,
    sanitize_drive_folder_name,
)


def test_pillar_folder_name_uses_display_value():
    assert pillar_folder_name(ContentPillar.JOB_SEARCH) == "Job Search"
    assert pillar_folder_name("Tech") == "Tech"


def test_raw_folder_setting_defaults_to_raw():
    assert Settings().raw_folder_name == "Raw"


def test_ensure_all_raw_pillar_folders_creates_raw_pillar_tree():
    class FakeDriveService(GoogleDriveService):
        def __init__(self):
            self.settings = Settings(google_drive_folder_id="root")
            self.calls = []

        def get_or_create_child_folder(self, parent_folder_id: str, folder_name: str) -> DriveFolderResult:
            self.calls.append((parent_folder_id, folder_name))
            return DriveFolderResult(
                folder_id=f"{parent_folder_id}/{folder_name}",
                name=folder_name,
                web_view_link=f"https://drive.google.com/drive/folders/{parent_folder_id}/{folder_name}",
            )

    drive = FakeDriveService()

    folders = drive.ensure_all_raw_pillar_folders()

    assert folders["Tech"] == "root/Raw/Tech"
    assert ("root", "Raw") in drive.calls
    assert ("root/Raw", "Gym") in drive.calls
    assert ("root/Raw", "Faith") in drive.calls


def test_escape_drive_query_value_escapes_quotes_and_backslashes():
    assert escape_drive_query_value("Faith's \\ folder") == "Faith\\'s \\\\ folder"


def test_inspiration_folder_name_uses_title_and_shortcode():
    assert (
        inspiration_folder_name("Unlocking Million-Dollar Apps with AI Coding Agents", "DYNOaRURJ77")
        == "Unlocking Million-Dollar Apps with AI Coding Agents - DYNOaRURJ77"
    )


def test_sanitize_drive_folder_name_removes_drive_unfriendly_characters():
    assert sanitize_drive_folder_name("Build / Ship: Fast?\nNow") == "Build Ship Fast Now"


def test_extract_drive_folder_id_from_folder_link():
    assert (
        extract_drive_folder_id_from_link("https://drive.google.com/drive/folders/10Y52LF6o39I1zxv4dspxmbaLPKK-4fPZ")
        == "10Y52LF6o39I1zxv4dspxmbaLPKK-4fPZ"
    )


def test_extract_drive_folder_id_from_query_link():
    assert extract_drive_folder_id_from_link("https://drive.google.com/open?id=folder_123") == "folder_123"
