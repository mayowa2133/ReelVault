from app.models.schemas import ContentPillar
from app.services.google_drive_service import (
    escape_drive_query_value,
    inspiration_folder_name,
    pillar_folder_name,
    sanitize_drive_folder_name,
)


def test_pillar_folder_name_uses_display_value():
    assert pillar_folder_name(ContentPillar.JOB_SEARCH) == "Job Search"
    assert pillar_folder_name("Tech") == "Tech"


def test_escape_drive_query_value_escapes_quotes_and_backslashes():
    assert escape_drive_query_value("Faith's \\ folder") == "Faith\\'s \\\\ folder"


def test_inspiration_folder_name_uses_title_and_shortcode():
    assert (
        inspiration_folder_name("Unlocking Million-Dollar Apps with AI Coding Agents", "DYNOaRURJ77")
        == "Unlocking Million-Dollar Apps with AI Coding Agents - DYNOaRURJ77"
    )


def test_sanitize_drive_folder_name_removes_drive_unfriendly_characters():
    assert sanitize_drive_folder_name("Build / Ship: Fast?\nNow") == "Build Ship Fast Now"
