from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import Settings
from app.models.schemas import ContentPillar, DriveUploadResult
from app.services.google_oauth_service import GOOGLE_DRIVE_SCOPE, GoogleOAuthCredentialsProvider
from app.utils.errors import ExternalServiceError


@dataclass(frozen=True)
class DriveFolderResult:
    folder_id: str
    name: str
    web_view_link: str


class GoogleDriveService:
    """Upload private reference files into a configured Google Drive folder."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.credentials_provider = GoogleOAuthCredentialsProvider(settings, scopes=[GOOGLE_DRIVE_SCOPE])
        self._service = None
        self._folder_cache: dict[tuple[str, str], DriveFolderResult] = {}

    def upload_file(
        self,
        file_path: Path,
        description: str | None = None,
        folder_id: str | None = None,
    ) -> DriveUploadResult:
        if not self.settings.google_drive_folder_id:
            raise ExternalServiceError("GOOGLE_DRIVE_FOLDER_ID is not configured", step="google_drive")
        if not file_path.exists():
            raise ExternalServiceError(f"File does not exist for Drive upload: {file_path}", step="google_drive")

        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        metadata = {
            "name": file_path.name,
            "parents": [folder_id or self.settings.google_drive_folder_id],
        }
        if description:
            metadata["description"] = description

        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
        created = (
            self._client()
            .files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,name,webViewLink,webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return DriveUploadResult(
            file_id=created["id"],
            name=created.get("name", file_path.name),
            web_view_link=created.get("webViewLink"),
            web_content_link=created.get("webContentLink"),
        )

    def get_or_create_pillar_folder(self, pillar: ContentPillar | str) -> str:
        if not self.settings.google_drive_folder_id:
            raise ExternalServiceError("GOOGLE_DRIVE_FOLDER_ID is not configured", step="google_drive")

        folder_name = pillar_folder_name(pillar)
        return self.get_or_create_child_folder(self.settings.google_drive_folder_id, folder_name).folder_id

    def get_or_create_used_folder(self, pillar: ContentPillar | str) -> DriveFolderResult:
        pillar_folder_id = self.get_or_create_pillar_folder(pillar)
        return self.get_or_create_child_folder(pillar_folder_id, self.settings.used_folder_name)

    def get_or_create_inspiration_folder(
        self,
        pillar: ContentPillar | str,
        title: str,
        shortcode: str | None = None,
    ) -> DriveFolderResult:
        pillar_folder_id = self.get_or_create_pillar_folder(pillar)
        folder_name = inspiration_folder_name(title=title, shortcode=shortcode)
        return self.get_or_create_child_folder(pillar_folder_id, folder_name)

    def get_or_create_child_folder(self, parent_folder_id: str, folder_name: str) -> DriveFolderResult:
        if not parent_folder_id:
            raise ExternalServiceError("Parent Google Drive folder ID is required", step="google_drive")
        folder_name = sanitize_drive_folder_name(folder_name)
        cache_key = (parent_folder_id, folder_name)
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        escaped_name = escape_drive_query_value(folder_name)
        escaped_parent = escape_drive_query_value(parent_folder_id)
        query = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{escaped_name}' "
            f"and '{escaped_parent}' in parents "
            "and trashed = false"
        )
        existing = (
            self._client()
            .files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id,name,webViewLink)",
                pageSize=1,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
            .get("files", [])
        )
        if existing:
            folder_id = existing[0]["id"]
            name = existing[0].get("name", folder_name)
            web_view_link = existing[0].get("webViewLink") or drive_folder_link(folder_id)
        else:
            created = (
                self._client()
                .files()
                .create(
                    body={
                        "name": folder_name,
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": [parent_folder_id],
                    },
                    fields="id,name,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            folder_id = created["id"]
            name = created.get("name", folder_name)
            web_view_link = created.get("webViewLink") or drive_folder_link(folder_id)

        folder = DriveFolderResult(folder_id=folder_id, name=name, web_view_link=web_view_link)
        self._folder_cache[cache_key] = folder
        return folder

    def ensure_all_pillar_folders(self) -> dict[str, str]:
        return {pillar.value: self.get_or_create_pillar_folder(pillar) for pillar in ContentPillar}

    def move_file_to_folder(self, file_id: str, folder_id: str) -> None:
        self.move_item_to_folder(file_id, folder_id)

    def move_item_to_folder(self, item_id: str, folder_id: str) -> None:
        if not item_id or not folder_id:
            return
        file = (
            self._client()
            .files()
            .get(fileId=item_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        parents = file.get("parents", [])
        if parents == [folder_id]:
            return
        previous_parents = ",".join(parent for parent in parents if parent != folder_id)
        self._client().files().update(
            fileId=item_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id,parents",
            supportsAllDrives=True,
        ).execute()

    def move_inspiration_folder_to_used(self, folder_id: str, pillar: ContentPillar | str) -> DriveFolderResult:
        used_folder = self.get_or_create_used_folder(pillar)
        self.move_item_to_folder(folder_id, used_folder.folder_id)
        return used_folder

    def move_inspiration_folder_to_pillar(self, folder_id: str, pillar: ContentPillar | str) -> str:
        pillar_folder_id = self.get_or_create_pillar_folder(pillar)
        self.move_item_to_folder(folder_id, pillar_folder_id)
        return pillar_folder_id

    def _client(self):
        if self._service is None:
            credentials = self.credentials_provider.get_credentials()
            self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service


def pillar_folder_name(pillar: ContentPillar | str) -> str:
    value = pillar.value if isinstance(pillar, ContentPillar) else str(pillar)
    return value.strip() or "Unclassified"


def inspiration_folder_name(title: str, shortcode: str | None = None) -> str:
    clean_title = sanitize_drive_folder_name(title or "Reel Inspiration")
    clean_shortcode = sanitize_drive_folder_name(shortcode or "")
    if clean_shortcode and clean_shortcode.lower() not in clean_title.lower():
        return f"{clean_title} - {clean_shortcode}"[:180].strip(" .-_")
    return clean_title[:180].strip(" .-_") or "Reel Inspiration"


def sanitize_drive_folder_name(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", str(value))
    value = re.sub(r"[<>:\"/\\|?*]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .-_")
    return value or "Reel Inspiration"


def drive_folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def extract_drive_folder_id_from_link(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None

    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        query_id = parse_qs(parsed.query).get("id")
        if query_id and query_id[0]:
            return query_id[0]
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
        if match:
            return match.group(1)

    if "/folders/" in value:
        return value.split("/folders/", 1)[1].split("?", 1)[0].split("/", 1)[0] or None

    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return None


def escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
