from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.schemas import DownloadResult
from app.utils.errors import DownloadFailedError, ExternalServiceError, public_error_message
from app.utils.logging import get_logger

try:
    import yt_dlp
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    yt_dlp = None  # type: ignore[assignment]

logger = get_logger(__name__)


class DownloaderService:
    """Best-effort Reel downloader behind a replaceable abstraction."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def download(self, url: str, output_dir: Path) -> DownloadResult:
        if not self.settings.enable_video_download:
            return DownloadResult(success=False, status="disabled", error_message="Video download is disabled")
        if yt_dlp is None:
            raise ExternalServiceError("yt-dlp is not installed", step="download")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "%(id)s.%(ext)s")
        options = self._yt_dlp_options(output_template, output_dir)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = resolve_downloaded_path(info, output_dir, ydl)
        except Exception as exc:
            reason = public_error_message(exc)
            logger.warning("reel_download_failed", extra={"error": reason})
            return DownloadResult(
                success=False,
                status="download_failed",
                error_message=(
                    "Download failed. The platform may require login, block automated requests, "
                    f"rate limit this link, or expose media that yt-dlp cannot access anonymously. Details: {reason}"
                ),
            )

        if not file_path or not file_path.exists():
            raise DownloadFailedError("yt-dlp reported success but no video file was found", step="download")

        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.settings.max_video_size_mb:
            file_path.unlink(missing_ok=True)
            return DownloadResult(
                success=False,
                status="download_failed",
                error_message=f"Downloaded video exceeded MAX_VIDEO_SIZE_MB ({size_mb:.1f} MB)",
            )

        metadata = compact_metadata(info)
        return DownloadResult(
            success=True,
            status="download_complete",
            file_path=file_path,
            creator_username=extract_creator_username(info),
            title=safe_str(info.get("title")),
            metadata=metadata,
        )

    def _yt_dlp_options(self, output_template: str, output_dir: Path) -> dict[str, Any]:
        options: dict[str, Any] = {
            "outtmpl": output_template,
            "format": "best[ext=mp4]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "cachedir": False,
            "retries": 1,
            "socket_timeout": 30,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            },
        }

        cookie_file = self._cookie_file(output_dir)
        if cookie_file:
            options["cookiefile"] = str(cookie_file)
        return options

    def _cookie_file(self, output_dir: Path) -> Path | None:
        if not self.settings.enable_auth_cookies:
            return None

        cookies_text = self.settings.social_cookies_text or self.settings.instagram_cookies_text
        if cookies_text:
            cookie_file = output_dir / "social_cookies.txt"
            cookie_file.write_text(cookies_text, encoding="utf-8")
            cookie_file.chmod(0o600)
            return cookie_file

        cookies_path = self.settings.social_cookies_file or self.settings.instagram_cookies_file
        if cookies_path:
            cookie_file = Path(cookies_path)
            if cookie_file.exists():
                return cookie_file
            logger.warning("social_cookies_file_missing", extra={"path": str(cookie_file)})
        return None


def resolve_downloaded_path(info: dict[str, Any], output_dir: Path, ydl: Any) -> Path | None:
    requested_downloads = info.get("requested_downloads") or []
    for item in requested_downloads:
        path = item.get("filepath")
        if path and Path(path).exists():
            return Path(path)

    prepared = Path(ydl.prepare_filename(info))
    if prepared.exists():
        return prepared

    mp4_prepared = prepared.with_suffix(".mp4")
    if mp4_prepared.exists():
        return mp4_prepared

    files = [path for path in output_dir.iterdir() if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def extract_creator_username(info: dict[str, Any]) -> str | None:
    candidates = [
        info.get("uploader_id"),
        info.get("uploader"),
        info.get("channel"),
        info.get("creator"),
        info.get("artist"),
    ]
    for candidate in candidates:
        value = safe_str(candidate)
        if value:
            return value.lstrip("@")
    return None


def compact_metadata(info: dict[str, Any]) -> dict[str, str | int | float | None]:
    keys = ["id", "title", "duration", "view_count", "like_count", "uploader", "uploader_id", "webpage_url"]
    return {key: info.get(key) for key in keys if key in info}


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
