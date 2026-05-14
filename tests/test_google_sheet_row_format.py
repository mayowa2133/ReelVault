from app.models.schemas import SHEET_COLUMNS, ProcessingStatus, ReelReference, SheetRow, TelegramMediaReference
from app.services.google_sheets_service import column_letter, last_data_row_from_key_values, merge_headers, pillar_tab_name


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
    assert values[SHEET_COLUMNS.index("Inspiration Folder Link")] == "https://drive.google.com/drive/folders/folder-id"


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
