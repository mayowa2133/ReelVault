from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.models.schemas import DownloadResult
from app.utils.errors import DownloadFailedError, ExternalServiceError, public_error_message
from app.utils.logging import get_logger

try:
    import yt_dlp
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    yt_dlp = None  # type: ignore[assignment]

logger = get_logger(__name__)


@dataclass(frozen=True)
class YoutubeNoAuthFallbackStrategy:
    name: str
    youtube_args: dict[str, list[str]]
    format_selector: str | None = None
    use_visitor_data: bool = False


YOUTUBE_FALLBACK_FORMAT = "18/best[ext=mp4]/bestvideo+bestaudio/best"
YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES = (
    YoutubeNoAuthFallbackStrategy(
        name="mweb_no_webpage_configs",
        youtube_args={
            "player_client": ["mweb"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="all_clients_no_webpage",
        youtube_args={
            "player_client": ["all"],
            "player_skip": ["webpage"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="all_clients_no_webpage_configs",
        youtube_args={
            "player_client": ["all"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="default_clients_with_visitor_data",
        youtube_args={
            "player_client": ["default"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
        use_visitor_data=True,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="all_clients_with_visitor_data",
        youtube_args={
            "player_client": ["all"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
        use_visitor_data=True,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="web_safari_no_webpage_configs",
        youtube_args={
            "player_client": ["web_safari"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
)


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
            info, file_path = self._download_with_options(url, output_dir, options)
        except Exception as exc:
            reason = public_error_message(exc)
            if should_retry_youtube_without_webpage(url, reason):
                info, file_path, fallback_error = self._download_with_youtube_fallbacks(
                    url,
                    output_dir,
                    options,
                    reason,
                )
                if fallback_error:
                    return self._download_failed_result(fallback_error)
            else:
                logger.warning("reel_download_failed", extra={"error": reason})
                return self._download_failed_result(reason)

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

    def _download_with_options(self, url: str, output_dir: Path, options: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            return info, resolve_downloaded_path(info, output_dir, ydl)

    def _download_failed_result(self, reason: str) -> DownloadResult:
        return DownloadResult(
            success=False,
            status="download_failed",
            error_message=(
                "Download failed. The platform may require login, block automated requests, "
                f"rate limit this link, or expose media that yt-dlp cannot access anonymously. Details: {reason}"
            ),
        )

    def _download_with_youtube_fallbacks(
        self,
        url: str,
        output_dir: Path,
        options: dict[str, Any],
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        attempt_errors = [("default", initial_reason)]
        youtube_visitor_data: str | None = None

        for strategy in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES:
            try:
                if strategy.use_visitor_data:
                    youtube_visitor_data = youtube_visitor_data or self._youtube_visitor_data()
                    if not youtube_visitor_data:
                        attempt_errors.append((strategy.name, "anonymous YouTube Visitor Data was unavailable"))
                        logger.warning(
                            "youtube_no_auth_fallback_skipped",
                            extra={"url": url, "strategy": strategy.name, "reason": "visitor_data_unavailable"},
                        )
                        continue

                fallback_options = self._youtube_no_auth_fallback_options(options, strategy, youtube_visitor_data)
                info, file_path = self._download_with_options(url, output_dir, fallback_options)
                logger.warning(
                    "youtube_download_succeeded_with_no_auth_fallback",
                    extra={"url": url, "strategy": strategy.name},
                )
                return info, file_path, None
            except Exception as fallback_exc:
                fallback_reason = public_error_message(fallback_exc)
                attempt_errors.append((strategy.name, fallback_reason))
                logger.warning(
                    "youtube_no_auth_fallback_failed",
                    extra={"url": url, "strategy": strategy.name, "error": fallback_reason},
                )

        logger.warning("reel_download_failed", extra={"error": summarize_attempt_errors(attempt_errors)})
        return {}, None, (
            f"{initial_reason}. YouTube no-auth fallback attempts also failed: "
            f"{summarize_attempt_errors(attempt_errors[1:])}"
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
            "http_headers": {"User-Agent": self._yt_dlp_user_agent()},
        }

        cookie_file = self._cookie_file(output_dir)
        if cookie_file:
            options["cookiefile"] = str(cookie_file)
        return options

    def _youtube_no_auth_fallback_options(
        self,
        options: dict[str, Any],
        strategy: YoutubeNoAuthFallbackStrategy = YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES[0],
        visitor_data: str | None = None,
    ) -> dict[str, Any]:
        fallback_options = dict(options)
        extractor_args = dict(fallback_options.get("extractor_args") or {})
        youtube_args = dict(extractor_args.get("youtube") or {})
        youtube_args.update(strategy.youtube_args)
        if strategy.use_visitor_data and visitor_data:
            youtube_args["visitor_data"] = [visitor_data]
        extractor_args["youtube"] = youtube_args
        fallback_options["extractor_args"] = {
            **extractor_args,
        }
        if strategy.format_selector:
            fallback_options["format"] = strategy.format_selector
        return fallback_options

    def _youtube_visitor_data(self) -> str | None:
        if self.settings.youtube_visitor_data:
            return self.settings.youtube_visitor_data

        try:
            return fetch_anonymous_youtube_visitor_data(
                timeout_seconds=self.settings.request_timeout_seconds,
                user_agent=self._yt_dlp_user_agent(),
            )
        except Exception as exc:
            logger.warning("youtube_visitor_data_fetch_failed", extra={"error": public_error_message(exc)})
            return None

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

    def _yt_dlp_user_agent(self) -> str:
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )


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


def fetch_anonymous_youtube_visitor_data(timeout_seconds: int, user_agent: str) -> str | None:
    headers = {"User-Agent": user_agent}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get("https://www.youtube.com/")
        response.raise_for_status()

    for pattern in (
        r'"visitorData"\s*:\s*"([^"]+)"',
        r'"VISITOR_DATA"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, response.text)
        if match:
            return match.group(1)
    return None


def summarize_attempt_errors(attempt_errors: list[tuple[str, str]]) -> str:
    return "; ".join(f"{name}: {short_error(reason)}" for name, reason in attempt_errors)


def short_error(reason: str, max_length: int = 300) -> str:
    compact = " ".join(reason.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 3]}..."


def should_retry_youtube_without_webpage(url: str, error_message: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        return False

    lowered = error_message.lower()
    return any(
        needle in lowered
        for needle in (
            "sign in to confirm",
            "not a bot",
            "use --cookies",
            "use --cookies-from-browser",
            "failed to extract any player response",
            "all player responses are invalid",
            "no video formats found",
            "http error 403",
            "youtube is requiring a captcha",
            "this content isn't available, try again later",
        )
    )
