from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.utils.errors import DownloadFailedError, public_error_message


@dataclass(frozen=True)
class CobaltDownloadResult:
    file_path: Path
    info: dict[str, Any]


class CobaltService:
    """Optional Cobalt API fallback for public media URLs."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def enabled(self) -> bool:
        return bool(self.settings.cobalt_api_base_url)

    def download(self, url: str, output_dir: Path) -> CobaltDownloadResult:
        if not self.settings.cobalt_api_base_url:
            raise DownloadFailedError("Cobalt API fallback is not configured", step="download")

        output_dir.mkdir(parents=True, exist_ok=True)
        request_url = cobalt_endpoint_url(self.settings.cobalt_api_base_url)
        headers = self._headers()
        payload = self._payload(url)

        try:
            with httpx.Client(timeout=self.settings.cobalt_timeout_seconds, follow_redirects=True) as client:
                response = client.post(request_url, json=payload, headers=headers)
                response.raise_for_status()
                response_data = response.json()
                download_url, filename = select_cobalt_download(response_data)
                file_path = unique_output_path(output_dir / safe_cobalt_filename(filename, url))
                self._download_media(client, download_url, file_path)
        except DownloadFailedError:
            raise
        except Exception as exc:
            raise DownloadFailedError(f"Cobalt API request failed: {public_error_message(exc)}", step="download") from exc

        return CobaltDownloadResult(
            file_path=file_path,
            info={
                "id": cobalt_source_id(url),
                "title": file_path.stem,
                "webpage_url": url,
                "extractor": "cobalt",
                "cobalt_status": response_data.get("status"),
                "cobalt_service": response_data.get("service"),
            },
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ReelVault/1.0",
        }
        if self.settings.cobalt_api_key:
            headers["Authorization"] = f"Api-Key {self.settings.cobalt_api_key}"
        return headers

    def _payload(self, url: str) -> dict[str, Any]:
        return {
            "url": url,
            "downloadMode": "auto",
            "filenameStyle": "basic",
            "videoQuality": self.settings.cobalt_video_quality,
            "disableMetadata": True,
            "alwaysProxy": True,
            "localProcessing": "disabled",
            "youtubeVideoContainer": "mp4",
            "youtubeVideoCodec": "h264",
            "allowH265": False,
        }

    def _download_media(self, client: httpx.Client, download_url: str, file_path: Path) -> None:
        max_bytes = self.settings.max_video_size_mb * 1024 * 1024
        total_bytes = 0

        try:
            with client.stream("GET", download_url, headers={"User-Agent": "ReelVault/1.0"}) as response:
                response.raise_for_status()
                with file_path.open("wb") as output_file:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise DownloadFailedError(
                                f"Cobalt download exceeded MAX_VIDEO_SIZE_MB ({self.settings.max_video_size_mb} MB)",
                                step="download",
                            )
                        output_file.write(chunk)
        except Exception:
            file_path.unlink(missing_ok=True)
            raise

        if not file_path.exists() or file_path.stat().st_size == 0:
            file_path.unlink(missing_ok=True)
            raise DownloadFailedError("Cobalt returned an empty media file", step="download")


def cobalt_endpoint_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def select_cobalt_download(response_data: dict[str, Any]) -> tuple[str, str | None]:
    status = response_data.get("status")

    if status in {"tunnel", "redirect"}:
        download_url = response_data.get("url")
        if not download_url:
            raise DownloadFailedError("Cobalt response did not include a download URL", step="download")
        return str(download_url), safe_str(response_data.get("filename"))

    if status == "picker":
        picker = response_data.get("picker") or []
        for item in picker:
            if item.get("type") == "video" and item.get("url"):
                return str(item["url"]), safe_str(item.get("filename") or response_data.get("filename"))
        raise DownloadFailedError("Cobalt returned a picker response without a video item", step="download")

    if status == "local-processing":
        raise DownloadFailedError(
            "Cobalt returned a local-processing response that ReelVault cannot consume directly",
            step="download",
        )

    if status == "error":
        error = response_data.get("error") or {}
        code = error.get("code") or "unknown_error"
        context = error.get("context") or {}
        context_text = f" ({context})" if context else ""
        raise DownloadFailedError(f"Cobalt returned error {code}{context_text}", step="download")

    raise DownloadFailedError(f"Cobalt returned unsupported status {status!r}", step="download")


def safe_cobalt_filename(filename: str | None, source_url: str) -> str:
    candidate = safe_str(filename) or f"{cobalt_source_id(source_url)}.mp4"
    candidate = candidate.encode("ascii", "ignore").decode("ascii")
    candidate = re.sub(r"[^A-Za-z0-9._ -]+", "_", candidate).strip(" ._-")
    if not candidate:
        candidate = f"{cobalt_source_id(source_url)}.mp4"
    if "." not in Path(candidate).name:
        candidate = f"{candidate}.mp4"
    return candidate


def cobalt_source_id(source_url: str) -> str:
    parsed = urlsplit(source_url)
    for part in reversed([item for item in parsed.path.split("/") if item]):
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", part).strip("_")
        if cleaned:
            return cleaned[:80]
    host = parsed.netloc.replace(".", "_") or "cobalt_media"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", host).strip("_")[:80] or "cobalt_media"


def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise DownloadFailedError(f"Could not allocate output path for {path.name}", step="download")


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
