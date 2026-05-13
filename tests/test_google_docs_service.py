from app.config import Settings
from app.models.schemas import SheetRow
from app.services.google_docs_service import GoogleDocsService


def test_script_doc_body_places_transcript_above_custom_script():
    row = SheetRow(
        reel_url="https://www.instagram.com/reel/ABC123/",
        shortcode="ABC123",
        script_title="My Original Version",
        transcript="This is the full source transcript.",
        custom_script="This is the generated script.",
    )

    body = GoogleDocsService(Settings())._doc_body(row)

    assert "Source Transcript\nThis is the full source transcript." in body
    assert body.index("Source Transcript") < body.index("Custom Script")
