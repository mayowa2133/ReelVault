from app.config import Settings, extract_google_drive_folder_id, extract_google_sheet_id


def test_extract_google_sheet_id_from_full_url():
    assert (
        extract_google_sheet_id("https://docs.google.com/spreadsheets/d/abc_123-XYZ/edit?gid=0#gid=0")
        == "abc_123-XYZ"
    )


def test_extract_google_sheet_id_from_id_with_edit_suffix():
    assert extract_google_sheet_id("abc_123-XYZ/edit?gid=0#gid=0") == "abc_123-XYZ"


def test_extract_google_drive_folder_id_from_full_url():
    assert extract_google_drive_folder_id("https://drive.google.com/drive/folders/folder_123-XYZ?usp=sharing") == (
        "folder_123-XYZ"
    )


def test_settings_normalizes_google_ids():
    settings = Settings(
        google_sheet_id="https://docs.google.com/spreadsheets/d/sheet_123/edit?gid=0#gid=0",
        google_drive_folder_id="https://drive.google.com/drive/folders/folder_123?usp=sharing",
    )

    assert settings.google_sheet_id == "sheet_123"
    assert settings.google_drive_folder_id == "folder_123"
