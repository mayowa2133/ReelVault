from app.models.schemas import SHEET_COLUMNS, ProcessingStatus, ReelReference, SheetRow, TelegramMediaReference
from app.services.google_sheets_service import (
    column_letter,
    has_active_processing_rows,
    last_data_row_from_key_values,
    merge_headers,
    pillar_tab_name,
    sheet_row_matches_reference,
    sort_rows_for_usage,
    used_sync_updates,
)


def test_sheet_row_values_match_header_count_and_order():
    reel = ReelReference(url="https://www.instagram.com/reel/ABC123/", shortcode="ABC123")
    row = SheetRow.from_reel(reel)
    row.status = ProcessingStatus.DOWNLOAD_STARTED.value
    row.hook = "A strong opening line"
    row.pillar = "Motivation"
    row.script_google_doc_link = "https://docs.google.com/document/d/doc-id/edit"
    row.inspiration_folder_link = "https://drive.google.com/drive/folders/folder-id"

    values = row.to_values()

    assert len(values) == len(SHEET_COLUMNS)
    assert values[SHEET_COLUMNS.index("Reel URL")] == "https://www.instagram.com/reel/ABC123/"
    assert values[SHEET_COLUMNS.index("Shortcode")] == "ABC123"
    assert values[SHEET_COLUMNS.index("Status")] == "download_started"
    assert values[SHEET_COLUMNS.index("Hook")] == "A strong opening line"
    assert values[SHEET_COLUMNS.index("Pillar")] == "Motivation"
    assert values[SHEET_COLUMNS.index("Script Google Doc Link")] == "https://docs.google.com/document/d/doc-id/edit"
    assert values[SHEET_COLUMNS.index("Used")] == "FALSE"
    assert values[SHEET_COLUMNS.index("Used At")] == ""
    assert values[SHEET_COLUMNS.index("Inspiration Folder Link")] == "https://drive.google.com/drive/folders/folder-id"
    assert values[SHEET_COLUMNS.index("Source Type")] == "instagram_url"


def test_sheet_row_source_type_tracks_provider():
    row = SheetRow.from_reel(
        ReelReference(url="https://www.youtube.com/watch?v=BaW_jenozKc", shortcode="BaW_jenozKc", provider="youtube")
    )

    assert row.source_type == "youtube_url"
    assert row.to_reel_reference().provider == "youtube"


def test_sheet_row_truncates_long_transcripts():
    row = SheetRow(reel_url="https://www.instagram.com/reel/ABC123/", transcript="x" * 50_000)

    transcript_value = row.to_values()[SHEET_COLUMNS.index("Transcript")]

    assert len(transcript_value) < 50_000
    assert "[truncated for Google Sheets]" in transcript_value


def test_sheet_row_can_round_trip_from_values():
    row = SheetRow(
        reel_url="https://www.instagram.com/reel/ABC123/",
        shortcode="ABC123",
        pillar="Tech",
        pillar_source="telegram_exact",
        custom_script="Line one.\nLine two.",
    )

    parsed = SheetRow.from_values(row.to_values())

    assert parsed.reel_url == row.reel_url
    assert parsed.pillar == "Tech"
    assert parsed.pillar_source == "telegram_exact"
    assert parsed.custom_script == "Line one.\nLine two."
    assert parsed.used == "FALSE"
    assert parsed.used_at == ""


def test_sheet_row_apply_used_state_sets_used_at_timestamp():
    row = SheetRow(reel_url="https://www.instagram.com/reel/ABC123/")

    row.apply_used_state(True, used_at="2026-05-16T10:00:00+00:00")

    assert row.used == "TRUE"
    assert row.used_at == "2026-05-16T10:00:00+00:00"

    row.apply_used_state(False)

    assert row.used == "FALSE"
    assert row.used_at == ""


def test_sheet_row_can_store_telegram_media_reference():
    media = TelegramMediaReference(
        file_id="file-123",
        file_unique_id="unique-123",
        file_name="upload.mp4",
        mime_type="video/mp4",
        file_size=1234,
    )
    row = SheetRow.from_telegram_media(
        ReelReference(url="telegram-upload://unique-123", shortcode="unique-123"),
        media,
    )

    parsed = SheetRow.from_values(row.to_values())

    assert parsed.source_type == "telegram_upload"
    assert parsed.telegram_file_id == "file-123"
    assert parsed.to_telegram_media_reference() == media


def test_column_letter_supports_dynamic_sheet_ranges():
    assert column_letter(1) == "A"
    assert column_letter(26) == "Z"
    assert column_letter(27) == "AA"


def test_merge_headers_appends_new_columns_without_reordering_existing_columns():
    old_headers = SHEET_COLUMNS[:26]

    merged = merge_headers(old_headers, SHEET_COLUMNS)

    assert merged[:26] == old_headers
    assert "Pillar" in merged
    assert "Script Google Doc Link" in merged
    assert "Used" in merged
    assert "Inspiration Folder Link" in merged
    assert "Used At" in merged


def test_pillar_tab_name_matches_pillar_display_name():
    assert pillar_tab_name("Morning Routine") == "Morning Routine"


def test_last_data_row_ignores_checkbox_only_rows():
    values = [
        ["Created At", "Reel URL"],
        ["2026-05-13T19:52:18+00:00", "https://www.instagram.com/reel/ABC/"],
        ["", ""],
        ["", ""],
    ]

    assert last_data_row_from_key_values(values) == 2


def test_last_data_row_keeps_far_real_rows():
    values = [
        ["Created At", "Reel URL"],
        ["2026-05-13T19:52:18+00:00", "https://www.instagram.com/reel/ABC/"],
        ["", ""],
        ["2026-05-13T20:00:00+00:00", "https://www.instagram.com/reel/XYZ/"],
    ]

    assert last_data_row_from_key_values(values) == 4


def test_sheet_row_matches_used_reference_by_folder_shortcode_or_url():
    row = SheetRow(
        reel_url="https://www.instagram.com/reel/ABC123/",
        shortcode="ABC123",
        inspiration_folder_link="https://drive.google.com/drive/folders/folder-id",
    )

    assert sheet_row_matches_reference(row, inspiration_folder_link="https://drive.google.com/drive/folders/folder-id")
    assert sheet_row_matches_reference(row, shortcode="ABC123")
    assert sheet_row_matches_reference(row, reel_url="https://www.instagram.com/reel/ABC123/")
    assert not sheet_row_matches_reference(row, shortcode="OTHER")


def test_used_sync_updates_matches_other_tabs_and_skips_edited_row():
    matching_reels_row = SheetRow(
        reel_url="https://www.instagram.com/reel/ABC123/",
        shortcode="ABC123",
        used="FALSE",
        inspiration_folder_link="https://drive.google.com/drive/folders/folder-id",
    )
    matching_pillar_row = matching_reels_row.model_copy()
    already_used_row = matching_reels_row.model_copy(update={"used": "TRUE"})
    other_row = SheetRow(reel_url="https://www.instagram.com/reel/XYZ/", shortcode="XYZ", used="FALSE")

    updates = used_sync_updates(
        {
            "Reels": [(2, matching_reels_row), (3, other_row)],
            "Motivation": [(5, matching_pillar_row), (6, already_used_row)],
        },
        used=True,
        inspiration_folder_link="https://drive.google.com/drive/folders/folder-id",
        shortcode="ABC123",
        reel_url="https://www.instagram.com/reel/ABC123/",
        edited_tab_name="Reels",
        edited_row_number=2,
    )

    assert updates == [("Motivation", 5)]


def test_used_sync_updates_refreshes_matching_used_at_values():
    matching_pillar_row = SheetRow(
        reel_url="https://www.instagram.com/reel/ABC123/",
        shortcode="ABC123",
        used="TRUE",
        used_at="",
        inspiration_folder_link="https://drive.google.com/drive/folders/folder-id",
    )

    updates = used_sync_updates(
        {"Motivation": [(5, matching_pillar_row)]},
        used=True,
        used_at="2026-05-16T10:00:00+00:00",
        inspiration_folder_link="https://drive.google.com/drive/folders/folder-id",
    )

    assert updates == [("Motivation", 5)]


def test_sort_rows_for_usage_keeps_active_newest_first_then_used_newest_first():
    old_active = SheetRow(
        reel_url="https://www.instagram.com/reel/OLD/",
        created_at="2026-05-14T10:00:00+00:00",
        shortcode="OLD",
        status=ProcessingStatus.COMPLETE.value,
    )
    new_active = SheetRow(
        reel_url="https://www.instagram.com/reel/NEW/",
        created_at="2026-05-16T10:00:00+00:00",
        shortcode="NEW",
        status=ProcessingStatus.COMPLETE.value,
    )
    old_used = SheetRow(
        reel_url="https://www.instagram.com/reel/USEDOLD/",
        created_at="2026-05-13T10:00:00+00:00",
        shortcode="USEDOLD",
        status=ProcessingStatus.COMPLETE.value,
        used="TRUE",
        used_at="2026-05-15T10:00:00+00:00",
    )
    new_used = SheetRow(
        reel_url="https://www.instagram.com/reel/USEDNEW/",
        created_at="2026-05-12T10:00:00+00:00",
        shortcode="USEDNEW",
        status=ProcessingStatus.COMPLETE.value,
        used="TRUE",
        used_at="2026-05-16T11:00:00+00:00",
    )

    sorted_rows = sort_rows_for_usage([old_used, old_active, new_used, new_active])

    assert [row.shortcode for row in sorted_rows] == ["NEW", "OLD", "USEDNEW", "USEDOLD"]


def test_has_active_processing_rows_detects_rows_that_should_not_be_reordered():
    assert has_active_processing_rows([SheetRow(reel_url="https://www.instagram.com/reel/ABC/", status="queued")])
    assert not has_active_processing_rows(
        [SheetRow(reel_url="https://www.instagram.com/reel/ABC/", status=ProcessingStatus.COMPLETE.value)]
    )
