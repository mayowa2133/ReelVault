from __future__ import annotations

from googleapiclient.discovery import build

from app.config import Settings
from app.models.schemas import GoogleDocResult, SheetRow
from app.services.google_oauth_service import GOOGLE_DOCS_SCOPE, GOOGLE_DRIVE_SCOPE, GoogleOAuthCredentialsProvider
from app.utils.errors import ExternalServiceError


GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"


class GoogleDocsService:
    """Create Google Docs for generated ReelVault scripts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.credentials_provider = GoogleOAuthCredentialsProvider(settings, scopes=[GOOGLE_DRIVE_SCOPE, GOOGLE_DOCS_SCOPE])
        self._drive_service = None
        self._docs_service = None

    def create_script_doc(self, row: SheetRow, folder_id: str | None = None) -> GoogleDocResult:
        if not self.settings.google_drive_folder_id:
            raise ExternalServiceError("GOOGLE_DRIVE_FOLDER_ID is not configured", step="google_docs")
        if not row.custom_script.strip():
            raise ExternalServiceError("Custom script is empty; cannot create Google Doc", step="google_docs")

        title = self._doc_title(row)
        created = (
            self._drive()
            .files()
            .create(
                body={
                    "name": title,
                    "mimeType": GOOGLE_DOC_MIME_TYPE,
                    "parents": [folder_id or self.settings.google_drive_folder_id],
                },
                fields="id,name,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )

        document_id = created["id"]
        self._docs().documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": self._doc_body(row)}}]},
        ).execute()

        return GoogleDocResult(
            document_id=document_id,
            title=created.get("name", title),
            web_view_link=created.get("webViewLink"),
        )

    def _drive(self):
        if self._drive_service is None:
            credentials = self.credentials_provider.get_credentials()
            self._drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._drive_service

    def _docs(self):
        if self._docs_service is None:
            credentials = self.credentials_provider.get_credentials()
            self._docs_service = build("docs", "v1", credentials=credentials, cache_discovery=False)
        return self._docs_service

    def _doc_title(self, row: SheetRow) -> str:
        shortcode = row.shortcode or "reel"
        script_title = row.script_title.strip() or "Custom Script"
        return f"{shortcode} - {script_title}"[:180]

    def _doc_body(self, row: SheetRow) -> str:
        parts = [
            row.script_title.strip() or "Custom Script",
            "",
            f"Source Video: {row.reel_url}",
        ]
        if row.pillar:
            parts.append(f"Pillar: {row.pillar}")
        if row.hook:
            parts.extend(["", "Source Hook", row.hook])
        if row.summary:
            parts.extend(["", "Summary", row.summary])
        if row.re_hooks:
            parts.extend(["", "Re-hooks", row.re_hooks])
        if row.transcript:
            parts.extend(["", "Source Transcript", row.transcript])

        parts.extend(["", "Custom Script", row.custom_script])
        return "\n".join(parts).strip() + "\n"
