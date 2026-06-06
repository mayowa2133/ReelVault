from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx

from app.config import Settings
from app.services.cobalt_service import unique_output_path
from app.utils.errors import DownloadFailedError, public_error_message


@dataclass(frozen=True)
class YoutubeMirrorDownloadResult:
    file_path: Path
    info: dict[str, Any]


@dataclass(frozen=True)
class MirrorStream:
    service: str
    url: str
    title: str | None
    author: str | None
    quality: str | None
    extension: str = "mp4"


class YoutubeMirrorService:
    """Optional no-auth fallback using configured Piped/Invidious API instances."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def enabled(self) -> bool:
        return bool(self.piped_base_urls() or self.invidious_base_urls())

    def piped_base_urls(self) -> list[str]:
        return parse_base_urls(self.settings.youtube_piped_api_base_urls)

    def invidious_base_urls(self) -> list[str]:
        return parse_base_urls(self.settings.youtube_invidious_base_urls)

    def download(self, url: str, output_dir: Path) -> YoutubeMirrorDownloadResult:
        video_id = youtube_video_id(url)
        if not video_id:
            raise DownloadFailedError("Could not determine YouTube video ID for mirror fallback", step="download")
        if not self.enabled():
            raise DownloadFailedError("YouTube mirror fallback is not configured", step="download")

        output_dir.mkdir(parents=True, exist_ok=True)
        attempt_errors: list[tuple[str, str]] = []

        with httpx.Client(timeout=self.settings.youtube_mirror_timeout_seconds, follow_redirects=True) as client:
            for base_url in self.piped_base_urls():
                try:
                    stream = self._piped_stream(client, base_url, video_id)
                    return self._download_stream(client, stream, video_id, url, output_dir)
                except Exception as exc:
                    attempt_errors.append((f"piped:{base_url}", public_error_message(exc)))

            for base_url in self.invidious_base_urls():
                try:
                    stream = self._invidious_stream(client, base_url, video_id)
                    return self._download_stream(client, stream, video_id, url, output_dir)
                except Exception as exc:
                    attempt_errors.append((f"invidious:{base_url}", public_error_message(exc)))

        raise DownloadFailedError(
            f"YouTube mirror fallback attempts failed: {summarize_mirror_attempts(attempt_errors)}",
            step="download",
        )

    def _piped_stream(self, client: httpx.Client, base_url: str, video_id: str) -> MirrorStream:
        response = client.get(piped_streams_url(base_url, video_id), headers=mirror_headers())
        response.raise_for_status()
        data = response.json()
        stream = select_piped_stream(data)
        if not stream:
            raise DownloadFailedError("Piped response did not include a downloadable progressive MP4 stream", step="download")
        return stream

    def _invidious_stream(self, client: httpx.Client, base_url: str, video_id: str) -> MirrorStream:
        response = client.get(
            invidious_video_url(base_url, video_id, self.settings.youtube_mirror_region),
            headers=mirror_headers(),
        )
        response.raise_for_status()
        data = response.json()
        stream = select_invidious_stream(data)
        if not stream:
            raise DownloadFailedError("Invidious response did not include a downloadable progressive MP4 stream", step="download")
        return stream

    def _download_stream(
        self,
        client: httpx.Client,
        stream: MirrorStream,
        video_id: str,
        source_url: str,
        output_dir: Path,
    ) -> YoutubeMirrorDownloadResult:
        file_path = unique_output_path(output_dir / safe_youtube_mirror_filename(video_id, stream.title, stream.extension))
        download_media_stream(
            client,
            stream.url,
            file_path,
            max_bytes=self.settings.max_video_size_mb * 1024 * 1024,
        )
        return YoutubeMirrorDownloadResult(
            file_path=file_path,
            info={
                "id": video_id,
                "title": stream.title or file_path.stem,
                "uploader": stream.author,
                "webpage_url": source_url,
                "extractor": "youtube_mirror",
                "youtube_mirror_service": stream.service,
                "format_note": stream.quality,
            },
        )


def parse_base_urls(value: str | None) -> list[str]:
    if not value:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[\n,]+", value):
        url = item.strip().rstrip("/")
        if not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def youtube_video_id(url: str) -> str | None:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        return first_path_part(parsed.path)
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        return None

    query_id = first_query_value(parse_qs(parsed.query), "v")
    if query_id:
        return query_id

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() in {"shorts", "live", "embed"}:
        return parts[1]
    return None


def piped_streams_url(base_url: str, video_id: str) -> str:
    return f"{base_url.rstrip('/')}/streams/{quote(video_id)}"


def invidious_video_url(base_url: str, video_id: str, region: str) -> str:
    query = urlencode({"local": "true", "region": region or "US"})
    return f"{base_url.rstrip('/')}/api/v1/videos/{quote(video_id)}?{query}"


def select_piped_stream(data: dict[str, Any]) -> MirrorStream | None:
    streams = data.get("videoStreams") or []
    candidates = [
        item
        for item in streams
        if item.get("url")
        and not truthy(item.get("videoOnly"))
        and is_mp4_stream(item)
    ]
    if not candidates:
        return None
    best = max(candidates, key=stream_height)
    return MirrorStream(
        service="piped",
        url=str(best["url"]),
        title=safe_str(data.get("title")),
        author=safe_str(data.get("uploader") or data.get("author")),
        quality=safe_str(best.get("quality") or best.get("qualityLabel")),
        extension=stream_extension(best),
    )


def select_invidious_stream(data: dict[str, Any]) -> MirrorStream | None:
    streams = data.get("formatStreams") or []
    candidates = [item for item in streams if item.get("url") and is_mp4_stream(item)]
    if not candidates:
        return None
    best = max(candidates, key=stream_height)
    return MirrorStream(
        service="invidious",
        url=str(best["url"]),
        title=safe_str(data.get("title")),
        author=safe_str(data.get("author") or data.get("uploader")),
        quality=safe_str(best.get("qualityLabel") or best.get("quality")),
        extension=stream_extension(best),
    )


def is_mp4_stream(item: dict[str, Any]) -> bool:
    container = safe_str(item.get("container") or item.get("format") or item.get("mimeType") or item.get("type"))
    if not container:
        return True
    normalized = re.sub(r"[^a-z0-9]+", "", container.lower())
    return "mp4" in normalized or "mpeg4" in normalized


def stream_extension(item: dict[str, Any]) -> str:
    container = safe_str(item.get("container") or item.get("format") or item.get("mimeType") or item.get("type"))
    if container and "webm" in container.lower():
        return "webm"
    return "mp4"


def stream_height(item: dict[str, Any]) -> int:
    for key in ("height", "qualityLabel", "resolution", "quality"):
        value = item.get(key)
        if value is None:
            continue
        match = re.search(r"(\d{3,4})", str(value))
        if match:
            return int(match.group(1))
    return 0


def safe_youtube_mirror_filename(video_id: str, title: str | None, extension: str) -> str:
    base = safe_str(title) or video_id
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" ._-")[:100]
    if not base:
        base = video_id
    extension = extension.strip(".") or "mp4"
    return f"{base}.{extension}"


def download_media_stream(client: httpx.Client, url: str, file_path: Path, max_bytes: int) -> None:
    total_bytes = 0
    try:
        with client.stream("GET", url, headers=mirror_headers()) as response:
            response.raise_for_status()
            with file_path.open("wb") as output_file:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise DownloadFailedError("YouTube mirror download exceeded MAX_VIDEO_SIZE_MB", step="download")
                    output_file.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    if not file_path.exists() or file_path.stat().st_size == 0:
        file_path.unlink(missing_ok=True)
        raise DownloadFailedError("YouTube mirror returned an empty media file", step="download")


def mirror_headers() -> dict[str, str]:
    return {"User-Agent": "ReelVault/1.0", "Accept": "*/*"}


def summarize_mirror_attempts(attempt_errors: list[tuple[str, str]]) -> str:
    if not attempt_errors:
        return "no configured mirror instances were attempted"
    return "; ".join(f"{name}: {short_error(reason)}" for name, reason in attempt_errors)


def short_error(reason: str, max_length: int = 240) -> str:
    compact = " ".join(reason.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 3]}..."


def first_path_part(path: str) -> str | None:
    for part in path.split("/"):
        if part:
            return part
    return None


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
