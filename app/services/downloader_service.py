from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import html
import json
import os
from pathlib import Path
import re
import random
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.config import Settings
from app.models.schemas import DownloadResult
from app.services.cobalt_service import CobaltService, parse_cobalt_base_urls, unique_output_path
from app.services.youtube_mirror_service import YoutubeMirrorService, youtube_video_id
from app.utils.errors import DownloadFailedError, ExternalServiceError, public_error_message
from app.utils.logging import get_logger

try:
    import yt_dlp
    from yt_dlp.networking.impersonate import ImpersonateTarget
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    yt_dlp = None  # type: ignore[assignment]
    ImpersonateTarget = None  # type: ignore[assignment]

logger = get_logger(__name__)


@dataclass(frozen=True)
class YoutubeNoAuthFallbackStrategy:
    name: str
    youtube_args: dict[str, list[str]]
    format_selector: str | None = None
    use_visitor_data: bool = False
    use_po_token: bool = False
    url_variant: str | None = None


@dataclass(frozen=True)
class XNoAuthFallbackStrategy:
    name: str
    twitter_args: dict[str, list[str]]


@dataclass(frozen=True)
class InstagramPublicDownloadResult:
    file_path: Path
    info: dict[str, Any]


@dataclass(frozen=True)
class TikTokPublicDownloadResult:
    file_path: Path
    info: dict[str, Any]


@dataclass(frozen=True)
class TikTokNoAuthFallbackStrategy:
    name: str
    app_name: str
    app_version: str
    manifest_app_version: str
    aid: str
    api_hostname: str


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
        name="android_ios_no_webpage_configs",
        youtube_args={
            "player_client": ["android", "ios"],
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
    YoutubeNoAuthFallbackStrategy(
        name="web_embedded_embed_url_no_webpage_configs",
        youtube_args={
            "player_client": ["web_embedded"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
        url_variant="embed",
    ),
    YoutubeNoAuthFallbackStrategy(
        name="tv_no_webpage_configs",
        youtube_args={
            "player_client": ["tv"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="android_vr_no_webpage_configs",
        youtube_args={
            "player_client": ["android_vr"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="web_creator_no_webpage_configs",
        youtube_args={
            "player_client": ["web_creator"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="web_music_no_webpage_configs",
        youtube_args={
            "player_client": ["web_music"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="tv_simply_no_webpage_configs",
        youtube_args={
            "player_client": ["tv_simply"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="tv_downgraded_no_webpage_configs",
        youtube_args={
            "player_client": ["tv_downgraded"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="web_with_configured_po_token",
        youtube_args={
            "player_client": ["web", "default"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
        use_visitor_data=True,
        use_po_token=True,
    ),
    YoutubeNoAuthFallbackStrategy(
        name="mweb_with_configured_po_token",
        youtube_args={
            "player_client": ["mweb"],
            "player_skip": ["webpage", "configs"],
        },
        format_selector=YOUTUBE_FALLBACK_FORMAT,
        use_visitor_data=True,
        use_po_token=True,
    ),
)

X_NO_AUTH_FALLBACK_STRATEGIES = (
    XNoAuthFallbackStrategy(
        name="legacy_api",
        twitter_args={"api": ["legacy"]},
    ),
)

TIKTOK_NO_AUTH_FALLBACK_STRATEGIES = (
    TikTokNoAuthFallbackStrategy(
        name="mobile_api_musical_ly_useast",
        app_name="musical_ly",
        app_version="35.1.3",
        manifest_app_version="2023501030",
        aid="0",
        api_hostname="api16-normal-c-useast1a.tiktokv.com",
    ),
    TikTokNoAuthFallbackStrategy(
        name="mobile_api_trill_alisg",
        app_name="trill",
        app_version="35.1.3",
        manifest_app_version="2023501030",
        aid="1180",
        api_hostname="api22-normal-c-alisg.tiktokv.com",
    ),
    TikTokNoAuthFallbackStrategy(
        name="mobile_api_musical_ly_alisg",
        app_name="musical_ly",
        app_version="35.1.3",
        manifest_app_version="2023501030",
        aid="0",
        api_hostname="api22-normal-c-alisg.tiktokv.com",
    ),
)


class DownloaderService:
    """Best-effort Reel downloader behind a replaceable abstraction."""

    def __init__(self, settings: Settings, yt_dlp_debug_log: list[str] | None = None):
        self.settings = settings
        self.yt_dlp_debug_log = yt_dlp_debug_log

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
                    info, file_path, fallback_error = self._download_with_youtube_mirror_fallback(
                        url,
                        output_dir,
                        fallback_error,
                    )
                    if fallback_error:
                        info, file_path, fallback_error = self._download_with_cobalt_fallback(
                            url,
                            output_dir,
                            fallback_error,
                        )
                        if fallback_error:
                            return self._download_failed_result(url, fallback_error)
            elif should_retry_tiktok_with_mobile_api(url, reason):
                info, file_path, fallback_error = self._download_with_tiktok_fallbacks(
                    url,
                    output_dir,
                    options,
                    reason,
                )
                if fallback_error:
                    info, file_path, fallback_error = self._download_with_tiktok_public_fallback(
                        url,
                        output_dir,
                        fallback_error,
                    )
                    if fallback_error:
                        info, file_path, fallback_error = self._download_with_cobalt_fallback(
                            url,
                            output_dir,
                            fallback_error,
                        )
                        if fallback_error:
                            return self._download_failed_result(url, fallback_error)
            elif should_retry_instagram_with_url_variants(url, reason):
                info, file_path, fallback_error = self._download_with_instagram_fallbacks(
                    url,
                    output_dir,
                    options,
                    reason,
                )
                if fallback_error:
                    info, file_path, fallback_error = self._download_with_instagram_public_fallback(
                        url,
                        output_dir,
                        fallback_error,
                    )
                    if fallback_error:
                        info, file_path, fallback_error = self._download_with_cobalt_fallback(
                            url,
                            output_dir,
                            fallback_error,
                        )
                        if fallback_error:
                            return self._download_failed_result(url, fallback_error)
            elif should_retry_x_with_api_fallbacks(url, reason):
                info, file_path, fallback_error = self._download_with_x_fallbacks(
                    url,
                    output_dir,
                    options,
                    reason,
                )
                if fallback_error:
                    info, file_path, fallback_error = self._download_with_cobalt_fallback(
                        url,
                        output_dir,
                        fallback_error,
                    )
                    if fallback_error:
                        return self._download_failed_result(url, fallback_error)
            else:
                info, file_path, fallback_error = self._download_with_youtube_mirror_fallback(
                    url,
                    output_dir,
                    reason,
                )
                if fallback_error:
                    info, file_path, fallback_error = self._download_with_cobalt_fallback(
                        url,
                        output_dir,
                        fallback_error,
                    )
                if fallback_error:
                    logger.warning("reel_download_failed", extra={"error": fallback_error})
                    return self._download_failed_result(url, fallback_error)

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

    def _download_failed_result(self, url: str, reason: str) -> DownloadResult:
        failure_guidance = download_failure_guidance(url, self.settings)
        guidance_text = format_download_failure_guidance(failure_guidance)
        details = f"{reason}{guidance_text}"
        return DownloadResult(
            success=False,
            status="download_failed",
            error_message=(
                "Download failed. The platform may require login, block automated requests, "
                f"rate limit this link, or expose media that yt-dlp cannot access anonymously. Details: {details}"
            ),
            failure_category=failure_guidance.get("category"),
            next_steps=list(failure_guidance.get("next_steps") or []),
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
                if strategy.use_po_token and not self.settings.youtube_po_token:
                    attempt_errors.append((strategy.name, "YOUTUBE_PO_TOKEN is not configured"))
                    logger.warning(
                        "youtube_no_auth_fallback_skipped",
                        extra={"url": url, "strategy": strategy.name, "reason": "po_token_unavailable"},
                    )
                    continue
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
                target_url = youtube_fallback_url(url, strategy.url_variant) or url
                info, file_path = self._download_with_options(target_url, output_dir, fallback_options)
                logger.warning(
                    "youtube_download_succeeded_with_no_auth_fallback",
                    extra={"url": url, "target_url": target_url, "strategy": strategy.name},
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

    def _download_with_tiktok_fallbacks(
        self,
        url: str,
        output_dir: Path,
        options: dict[str, Any],
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        attempt_errors = [("default", initial_reason)]
        fallback_urls: list[tuple[str, str]] = [("default", url)]

        if is_tiktok_short_url(url):
            try:
                redirect_url = fetch_tiktok_redirect_url(
                    url,
                    timeout_seconds=self.settings.request_timeout_seconds,
                    user_agent=self._yt_dlp_user_agent(),
                )
                if redirect_url:
                    fallback_urls = dedupe_named_urls(
                        [
                            ("tiktok_short_redirect_url", redirect_url),
                            *fallback_urls,
                        ]
                    )
                    try:
                        info, file_path = self._download_with_options(redirect_url, output_dir, dict(options))
                        logger.warning(
                            "tiktok_download_succeeded_with_redirect_fallback",
                            extra={"url": url, "redirect_url": redirect_url},
                        )
                        return info, file_path, None
                    except Exception as redirect_download_exc:
                        redirect_download_reason = public_error_message(redirect_download_exc)
                        attempt_errors.append(("tiktok_short_redirect_url", redirect_download_reason))
                        logger.warning(
                            "tiktok_short_redirect_download_failed",
                            extra={"url": url, "redirect_url": redirect_url, "error": redirect_download_reason},
                        )
            except Exception as redirect_exc:
                redirect_reason = public_error_message(redirect_exc)
                attempt_errors.append(("tiktok_short_redirect_url", redirect_reason))
                logger.warning("tiktok_short_redirect_fallback_failed", extra={"url": url, "error": redirect_reason})

        for target_name, target_url in fallback_urls:
            for strategy in TIKTOK_NO_AUTH_FALLBACK_STRATEGIES:
                attempt_name = strategy.name if target_name == "default" else f"{target_name}_{strategy.name}"
                try:
                    fallback_options = self._tiktok_no_auth_fallback_options(options, strategy)
                    info, file_path = self._download_with_options(target_url, output_dir, fallback_options)
                    logger.warning(
                        "tiktok_download_succeeded_with_mobile_api_fallback",
                        extra={"url": target_url, "original_url": url, "strategy": attempt_name},
                    )
                    return info, file_path, None
                except Exception as fallback_exc:
                    fallback_reason = public_error_message(fallback_exc)
                    attempt_errors.append((attempt_name, fallback_reason))
                    logger.warning(
                        "tiktok_mobile_api_fallback_failed",
                        extra={"url": target_url, "original_url": url, "strategy": attempt_name, "error": fallback_reason},
                    )

        return {}, None, (
            f"{initial_reason}. TikTok no-auth mobile API fallback attempts also failed: "
            f"{summarize_attempt_errors(attempt_errors[1:])}"
        )

    def _download_with_tiktok_public_fallback(
        self,
        url: str,
        output_dir: Path,
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        if provider_host(url) not in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
            return {}, None, initial_reason

        try:
            public_result = download_tiktok_public_media(
                url,
                output_dir,
                self.settings,
                user_agent=self._yt_dlp_user_agent(),
            )
            logger.warning("tiktok_download_succeeded_with_public_media_fallback", extra={"url": url})
            return public_result.info, public_result.file_path, None
        except Exception as public_exc:
            public_reason = public_error_message(public_exc)
            logger.warning("tiktok_public_media_fallback_failed", extra={"url": url, "error": public_reason})
            return {}, None, f"{initial_reason}. TikTok public media fallback failed: {public_reason}"

    def _download_with_instagram_fallbacks(
        self,
        url: str,
        output_dir: Path,
        options: dict[str, Any],
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        attempt_errors = [("default", initial_reason)]
        fallback_urls = instagram_fallback_urls(url)

        if is_instagram_share_url(url):
            try:
                redirect_url = fetch_instagram_redirect_url(
                    url,
                    timeout_seconds=self.settings.request_timeout_seconds,
                    user_agent=self._yt_dlp_user_agent(),
                )
                if redirect_url:
                    fallback_urls = [
                        ("instagram_share_redirect_url", redirect_url),
                        *instagram_fallback_urls(redirect_url),
                        *fallback_urls,
                    ]
            except Exception as redirect_exc:
                redirect_reason = public_error_message(redirect_exc)
                attempt_errors.append(("instagram_share_redirect_url", redirect_reason))
                logger.warning("instagram_share_redirect_fallback_failed", extra={"url": url, "error": redirect_reason})

        if not fallback_urls:
            return {}, None, initial_reason

        for strategy_name, fallback_url in fallback_urls:
            try:
                info, file_path = self._download_with_options(fallback_url, output_dir, dict(options))
                logger.warning(
                    "instagram_download_succeeded_with_url_variant_fallback",
                    extra={"url": url, "strategy": strategy_name, "fallback_url": fallback_url},
                )
                return info, file_path, None
            except Exception as fallback_exc:
                fallback_reason = public_error_message(fallback_exc)
                attempt_errors.append((strategy_name, fallback_reason))
                logger.warning(
                    "instagram_url_variant_fallback_failed",
                    extra={"url": url, "strategy": strategy_name, "fallback_url": fallback_url, "error": fallback_reason},
                )

        return {}, None, (
            f"{initial_reason}. Instagram no-auth URL variant fallback attempts also failed: "
            f"{summarize_attempt_errors(attempt_errors[1:])}"
        )

    def _download_with_instagram_public_fallback(
        self,
        url: str,
        output_dir: Path,
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        if provider_host(url) != "instagram.com":
            return {}, None, initial_reason

        try:
            public_result = download_instagram_public_media(
                url,
                output_dir,
                self.settings,
                user_agent=self._yt_dlp_user_agent(),
            )
            logger.warning("instagram_download_succeeded_with_public_media_fallback", extra={"url": url})
            return public_result.info, public_result.file_path, None
        except Exception as public_exc:
            public_reason = public_error_message(public_exc)
            logger.warning("instagram_public_media_fallback_failed", extra={"url": url, "error": public_reason})
            return {}, None, f"{initial_reason}. Instagram public media fallback failed: {public_reason}"

    def _download_with_x_fallbacks(
        self,
        url: str,
        output_dir: Path,
        options: dict[str, Any],
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        attempt_errors = [("default", initial_reason)]
        fallback_urls = x_fallback_urls(url)

        for strategy_name, fallback_url in fallback_urls:
            try:
                info, file_path = self._download_with_options(fallback_url, output_dir, dict(options))
                logger.warning(
                    "x_download_succeeded_with_url_variant_fallback",
                    extra={"url": url, "strategy": strategy_name, "fallback_url": fallback_url},
                )
                return info, file_path, None
            except Exception as fallback_exc:
                fallback_reason = public_error_message(fallback_exc)
                attempt_errors.append((strategy_name, fallback_reason))
                logger.warning(
                    "x_url_variant_fallback_failed",
                    extra={"url": url, "strategy": strategy_name, "fallback_url": fallback_url, "error": fallback_reason},
                )

        for target_name, target_url in [("default", url), *fallback_urls]:
            for strategy in X_NO_AUTH_FALLBACK_STRATEGIES:
                attempt_name = strategy.name if target_name == "default" else f"{target_name}_{strategy.name}"
                try:
                    fallback_options = self._x_no_auth_fallback_options(options, strategy)
                    info, file_path = self._download_with_options(target_url, output_dir, fallback_options)
                    logger.warning(
                        "x_download_succeeded_with_api_fallback",
                        extra={"url": target_url, "original_url": url, "strategy": attempt_name},
                    )
                    return info, file_path, None
                except Exception as fallback_exc:
                    fallback_reason = public_error_message(fallback_exc)
                    attempt_errors.append((attempt_name, fallback_reason))
                    logger.warning(
                        "x_api_fallback_failed",
                        extra={"url": target_url, "original_url": url, "strategy": attempt_name, "error": fallback_reason},
                    )

        return {}, None, (
            f"{initial_reason}. X/Twitter no-auth URL/API fallback attempts also failed: "
            f"{summarize_attempt_errors(attempt_errors[1:])}"
        )

    def _download_with_cobalt_fallback(
        self,
        url: str,
        output_dir: Path,
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        if not should_try_cobalt_fallback(url) or not self.settings.cobalt_api_base_url:
            return {}, None, initial_reason

        try:
            cobalt_result = CobaltService(self.settings).download(url, output_dir)
            logger.warning("provider_download_succeeded_with_cobalt_fallback", extra={"url": url})
            return cobalt_result.info, cobalt_result.file_path, None
        except Exception as cobalt_exc:
            cobalt_reason = public_error_message(cobalt_exc)
            logger.warning("cobalt_fallback_failed", extra={"url": url, "error": cobalt_reason})
            return {}, None, f"{initial_reason}. Cobalt fallback failed: {cobalt_reason}"

    def _download_with_youtube_mirror_fallback(
        self,
        url: str,
        output_dir: Path,
        initial_reason: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        if provider_host(url) not in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
            return {}, None, initial_reason
        if not (self.settings.youtube_piped_api_base_urls or self.settings.youtube_invidious_base_urls):
            return {}, None, initial_reason

        try:
            mirror_result = YoutubeMirrorService(self.settings).download(url, output_dir)
            logger.warning("youtube_download_succeeded_with_mirror_fallback", extra={"url": url})
            return mirror_result.info, mirror_result.file_path, None
        except Exception as mirror_exc:
            mirror_reason = public_error_message(mirror_exc)
            logger.warning("youtube_mirror_fallback_failed", extra={"url": url, "error": mirror_reason})
            return {}, None, f"{initial_reason}. YouTube mirror fallback failed: {mirror_reason}"

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
            "retries": self.settings.yt_dlp_retries,
            "socket_timeout": self.settings.yt_dlp_socket_timeout_seconds,
            "http_headers": self._yt_dlp_headers(),
        }

        extractor_args = self._configured_extractor_args()
        if extractor_args:
            options["extractor_args"] = extractor_args
        if self.settings.social_download_proxy_url:
            options["proxy"] = self.settings.social_download_proxy_url
        if self.settings.social_download_source_address:
            options["source_address"] = self.settings.social_download_source_address
        if self.settings.yt_dlp_impersonate_client:
            impersonate = yt_dlp_impersonate_value(self.settings.yt_dlp_impersonate_client)
            if impersonate:
                options["impersonate"] = impersonate
        if self.settings.yt_dlp_extractor_retries is not None:
            options["extractor_retries"] = self.settings.yt_dlp_extractor_retries
        if self.settings.yt_dlp_fragment_retries is not None:
            options["fragment_retries"] = self.settings.yt_dlp_fragment_retries
        if self.settings.yt_dlp_file_access_retries is not None:
            options["file_access_retries"] = self.settings.yt_dlp_file_access_retries
        if self.settings.yt_dlp_retry_sleep_seconds is not None:
            options["retry_sleep_functions"] = retry_sleep_functions(self.settings.yt_dlp_retry_sleep_seconds)
        if self.settings.yt_dlp_sleep_requests_seconds is not None:
            options["sleep_interval_requests"] = self.settings.yt_dlp_sleep_requests_seconds
        if self.settings.yt_dlp_sleep_interval_seconds is not None:
            options["sleep_interval"] = self.settings.yt_dlp_sleep_interval_seconds
            if self.settings.yt_dlp_max_sleep_interval_seconds is not None:
                options["max_sleep_interval"] = self.settings.yt_dlp_max_sleep_interval_seconds

        if self.yt_dlp_debug_log is not None:
            options["logger"] = YtDlpCaptureLogger(self.yt_dlp_debug_log)
            options["verbose"] = True
            options["quiet"] = False
            options["no_warnings"] = False

        cookie_file = self._cookie_file(output_dir)
        if cookie_file:
            options["cookiefile"] = str(cookie_file)
        return options

    def _yt_dlp_headers(self) -> dict[str, str]:
        headers = {"User-Agent": self._yt_dlp_user_agent()}
        if self.settings.social_download_accept_language:
            headers["Accept-Language"] = self.settings.social_download_accept_language
        return headers

    def _configured_extractor_args(self) -> dict[str, dict[str, list[str]]]:
        youtube_args: dict[str, list[str]] = {}

        if self.settings.youtube_fetch_pot_policy:
            fetch_pot_policy = self.settings.youtube_fetch_pot_policy.strip().lower()
            if fetch_pot_policy in {"never", "auto", "always"}:
                youtube_args["fetch_pot"] = [fetch_pot_policy]
            else:
                logger.warning(
                    "invalid_youtube_fetch_pot_policy",
                    extra={"value": self.settings.youtube_fetch_pot_policy},
                )
        if self.settings.youtube_include_missing_pot_formats:
            youtube_args["formats"] = ["missing_pot"]
        if self.settings.youtube_use_ad_playback_context:
            youtube_args["use_ad_playback_context"] = ["true"]

        base_args: dict[str, dict[str, list[str]]] = {}
        if youtube_args:
            base_args["youtube"] = youtube_args
        if self.settings.youtube_pot_bgutil_base_url:
            base_args["youtubepot-bgutilhttp"] = {"base_url": [self.settings.youtube_pot_bgutil_base_url]}
        if self.settings.youtube_pot_bgutil_script_server_home:
            base_args["youtubepot-bgutilscript"] = {
                "server_home": [self.settings.youtube_pot_bgutil_script_server_home],
            }

        custom_args = parse_extractor_args_json(self.settings.social_extractor_args_json)
        return merge_extractor_args(base_args, custom_args)

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
        if strategy.use_po_token and self.settings.youtube_po_token:
            youtube_args["po_token"] = [self.settings.youtube_po_token]
        extractor_args["youtube"] = youtube_args
        fallback_options["extractor_args"] = {
            **extractor_args,
        }
        if strategy.format_selector:
            fallback_options["format"] = strategy.format_selector
        return fallback_options

    def _tiktok_no_auth_fallback_options(
        self,
        options: dict[str, Any],
        strategy: TikTokNoAuthFallbackStrategy = TIKTOK_NO_AUTH_FALLBACK_STRATEGIES[0],
    ) -> dict[str, Any]:
        fallback_options = dict(options)
        extractor_args = dict(fallback_options.get("extractor_args") or {})
        tiktok_args = dict(extractor_args.get("tiktok") or {})
        tiktok_args.update(
            {
                "app_info": [tiktok_app_info(strategy)],
                "api_hostname": [strategy.api_hostname],
                "device_id": [tiktok_device_id()],
            }
        )
        extractor_args["tiktok"] = tiktok_args
        fallback_options["extractor_args"] = extractor_args
        fallback_options["format"] = "best[ext=mp4]/best"
        return fallback_options

    def _x_no_auth_fallback_options(
        self,
        options: dict[str, Any],
        strategy: XNoAuthFallbackStrategy = X_NO_AUTH_FALLBACK_STRATEGIES[0],
    ) -> dict[str, Any]:
        fallback_options = dict(options)
        extractor_args = dict(fallback_options.get("extractor_args") or {})
        twitter_args = dict(extractor_args.get("twitter") or {})
        twitter_args.update(strategy.twitter_args)
        extractor_args["twitter"] = twitter_args
        fallback_options["extractor_args"] = extractor_args
        fallback_options["format"] = "best[ext=mp4]/best"
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
        if self.settings.social_download_user_agent:
            return self.settings.social_download_user_agent

        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )


def downloader_runtime_info(settings: Settings) -> dict[str, Any]:
    version = None
    if yt_dlp is not None:
        version = getattr(getattr(yt_dlp, "version", None), "__version__", None)

    return {
        "yt_dlp_available": yt_dlp is not None,
        "yt_dlp_version": version,
        "yt_dlp_package_spec": os.getenv("REELVAULT_YT_DLP_PACKAGE_SPEC") or None,
        "yt_dlp_plugin_package_specs": os.getenv("REELVAULT_YT_DLP_PLUGIN_PACKAGE_SPECS") or None,
        "youtube_po_token_provider_version": os.getenv("REELVAULT_YOUTUBE_PO_TOKEN_PROVIDER_VERSION") or None,
        "auth_cookies_enabled": settings.enable_auth_cookies,
        "cobalt_configured": bool(settings.cobalt_api_base_url),
        "cobalt_api_base_url_count": len(parse_cobalt_base_urls(settings.cobalt_api_base_url)),
        "proxy_configured": bool(settings.social_download_proxy_url),
        "impersonation_configured": bool(settings.yt_dlp_impersonate_client),
        "custom_extractor_args_configured": bool(settings.social_extractor_args_json),
        "youtube_visitor_data_configured": bool(settings.youtube_visitor_data),
        "youtube_po_token_configured": bool(settings.youtube_po_token),
        "youtube_fetch_pot_policy": settings.youtube_fetch_pot_policy,
        "youtube_pot_bgutil_base_url_configured": bool(settings.youtube_pot_bgutil_base_url),
        "youtube_pot_bgutil_script_server_home_configured": bool(settings.youtube_pot_bgutil_script_server_home),
        **youtube_pot_bgutil_http_provider_runtime_info(settings.youtube_pot_bgutil_base_url),
        "youtube_mirror_configured": bool(settings.youtube_piped_api_base_urls or settings.youtube_invidious_base_urls),
        "youtube_piped_configured": bool(settings.youtube_piped_api_base_urls),
        "youtube_invidious_configured": bool(settings.youtube_invidious_base_urls),
        "youtube_no_auth_fallback_strategy_count": len(YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES),
        "instagram_public_media_fallback_enabled": True,
        "tiktok_no_auth_fallback_strategy_count": len(TIKTOK_NO_AUTH_FALLBACK_STRATEGIES),
        "tiktok_public_media_fallback_enabled": True,
        "x_no_auth_fallback_strategy_count": len(X_NO_AUTH_FALLBACK_STRATEGIES),
        "custom_user_agent_configured": bool(settings.social_download_user_agent),
        "custom_accept_language_configured": bool(settings.social_download_accept_language),
        "yt_dlp_retries": settings.yt_dlp_retries,
        "yt_dlp_extractor_retries": settings.yt_dlp_extractor_retries,
        "yt_dlp_fragment_retries": settings.yt_dlp_fragment_retries,
        "yt_dlp_file_access_retries": settings.yt_dlp_file_access_retries,
        "yt_dlp_retry_sleep_configured": settings.yt_dlp_retry_sleep_seconds is not None,
        "yt_dlp_socket_timeout_seconds": settings.yt_dlp_socket_timeout_seconds,
        **youtube_po_token_provider_runtime_info(),
    }


def youtube_pot_bgutil_http_provider_runtime_info(base_url: str | None) -> dict[str, Any]:
    if not base_url:
        return {
            "youtube_pot_bgutil_http_provider_reachable": None,
            "youtube_pot_bgutil_http_provider_status": None,
            "youtube_pot_bgutil_http_provider_version": None,
            "youtube_pot_bgutil_http_provider_error": None,
        }

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/ping", timeout=0.75)
        provider_version = None
        if response.headers.get("content-type", "").startswith("application/json"):
            provider_version = response.json().get("version")

        return {
            "youtube_pot_bgutil_http_provider_reachable": response.status_code == 200,
            "youtube_pot_bgutil_http_provider_status": response.status_code,
            "youtube_pot_bgutil_http_provider_version": provider_version,
            "youtube_pot_bgutil_http_provider_error": None if response.status_code == 200 else short_error(response.text),
        }
    except Exception as exc:
        return {
            "youtube_pot_bgutil_http_provider_reachable": False,
            "youtube_pot_bgutil_http_provider_status": None,
            "youtube_pot_bgutil_http_provider_version": None,
            "youtube_pot_bgutil_http_provider_error": short_error(public_error_message(exc)),
        }


@lru_cache(maxsize=1)
def youtube_po_token_provider_runtime_info() -> dict[str, Any]:
    if yt_dlp is None:
        return {
            "youtube_po_token_provider_plugins_available": False,
            "youtube_po_token_provider_plugins": [],
            "youtube_po_token_provider_error": "yt-dlp is not installed",
        }

    try:
        from yt_dlp.extractor import import_extractors
        from yt_dlp.extractor.youtube.pot._provider import BuiltinIEContentProvider
        from yt_dlp.extractor.youtube.pot._registry import _pot_providers
        from yt_dlp.plugins import load_all_plugins

        import_extractors()
        load_all_plugins()

        providers: list[str] = []
        for provider in _pot_providers.value.values():
            if issubclass(provider, BuiltinIEContentProvider):
                continue
            name = str(getattr(provider, "PROVIDER_NAME", provider.__name__))
            version = getattr(provider, "PROVIDER_VERSION", None)
            providers.append(f"{name}-{version}" if version else name)

        providers = sorted(set(providers))
        return {
            "youtube_po_token_provider_plugins_available": bool(providers),
            "youtube_po_token_provider_plugins": providers,
            "youtube_po_token_provider_error": None,
        }
    except Exception as exc:  # pragma: no cover - depends on yt-dlp internals
        return {
            "youtube_po_token_provider_plugins_available": False,
            "youtube_po_token_provider_plugins": [],
            "youtube_po_token_provider_error": short_error(public_error_message(exc)),
        }


class YtDlpCaptureLogger:
    def __init__(self, lines: list[str]):
        self.lines = lines

    def debug(self, message: str) -> None:
        self._append("debug", message)

    def info(self, message: str) -> None:
        self._append("info", message)

    def warning(self, message: str) -> None:
        self._append("warning", message)

    def error(self, message: str) -> None:
        self._append("error", message)

    def _append(self, level: str, message: str) -> None:
        self.lines.append(f"{level}: {sanitize_yt_dlp_debug_message(str(message))}")


def sanitize_yt_dlp_debug_message(message: str) -> str:
    replacements = (
        (r'("poToken"\s*:\s*")[^"]+(")', r"\1[REDACTED]\2"),
        (r"('poToken'\s*:\s*')[^']+(')", r"\1[REDACTED]\2"),
        (r"(?i)(po[_-]?token\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)([?&]pot=)[^&\s]+", r"\1[REDACTED]"),
        (r"(?i)(/pot/)[^/?#\s]+", r"\1[REDACTED]"),
        (r"(?i)(Authorization:\s*)[^\n]+", r"\1[REDACTED]"),
        (r"(?i)(Cookie:\s*)[^\n]+", r"\1[REDACTED]"),
    )
    sanitized = message
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized


def compact_yt_dlp_debug_log(lines: list[str], max_chars: int) -> str:
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    omitted_chars = len(text) - max_chars
    return f"[truncated {omitted_chars} chars]\n{text[-max_chars:]}"


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
    keys = [
        "id",
        "title",
        "duration",
        "view_count",
        "like_count",
        "uploader",
        "uploader_id",
        "webpage_url",
        "extractor",
        "cobalt_status",
        "cobalt_service",
        "youtube_mirror_service",
        "format_note",
    ]
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


def youtube_fallback_url(url: str, variant: str | None) -> str | None:
    if not variant:
        return url
    if variant == "embed":
        video_id = youtube_video_id(url)
        if video_id:
            return f"https://www.youtube.com/embed/{quote(video_id, safe='')}?html5=1"
    return None


def parse_extractor_args_json(value: str | None) -> dict[str, dict[str, list[str]]]:
    if not value:
        return {}

    try:
        raw_args = json.loads(value)
    except json.JSONDecodeError as exc:
        logger.warning("invalid_social_extractor_args_json", extra={"error": str(exc)})
        return {}

    if not isinstance(raw_args, dict):
        logger.warning("invalid_social_extractor_args_json", extra={"error": "top-level value must be an object"})
        return {}

    return normalize_extractor_args(raw_args)


def normalize_extractor_args(raw_args: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    normalized: dict[str, dict[str, list[str]]] = {}
    for extractor_key, extractor_values in raw_args.items():
        if not isinstance(extractor_values, dict):
            logger.warning(
                "invalid_social_extractor_args_json",
                extra={"extractor": str(extractor_key), "error": "extractor value must be an object"},
            )
            continue

        normalized_values: dict[str, list[str]] = {}
        for arg_key, arg_value in extractor_values.items():
            normalized_values[normalize_extractor_arg_key(arg_key)] = normalize_extractor_arg_values(arg_value)

        if normalized_values:
            normalized[str(extractor_key).strip().lower()] = normalized_values
    return normalized


def merge_extractor_args(*extractor_args: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    merged: dict[str, dict[str, list[str]]] = {}
    for extractor_arg in extractor_args:
        for extractor_key, extractor_values in extractor_arg.items():
            existing_values = dict(merged.get(extractor_key) or {})
            existing_values.update(extractor_values)
            merged[extractor_key] = existing_values
    return merged


def normalize_extractor_arg_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def normalize_extractor_arg_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def yt_dlp_impersonate_value(value: str) -> Any | None:
    if ImpersonateTarget is None:
        return None

    normalized = value.strip()
    if normalized.lower() in {"any", "default"}:
        return ImpersonateTarget()

    try:
        return ImpersonateTarget.from_str(normalized.lower())
    except ValueError as exc:
        logger.warning("invalid_yt_dlp_impersonate_client", extra={"value": value, "error": str(exc)})
        return None


def retry_sleep_functions(seconds: float) -> dict[str, Any]:
    def sleep_func(_: int) -> float:
        return seconds

    return {
        "http": sleep_func,
        "fragment": sleep_func,
        "file_access": sleep_func,
        "extractor": sleep_func,
    }


def tiktok_app_info(strategy: TikTokNoAuthFallbackStrategy) -> str:
    return "/".join(
        (
            tiktok_install_id(),
            strategy.app_name,
            strategy.app_version,
            strategy.manifest_app_version,
            strategy.aid,
        )
    )


def tiktok_install_id() -> str:
    return str(random.randint(7250000000000000000, 7325099899999994577))


def tiktok_device_id() -> str:
    return str(random.randint(7250000000000000000, 7325099899999994577))


def instagram_fallback_urls(url: str) -> list[tuple[str, str]]:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "instagram.com":
        return []

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() not in {"reel", "reels", "p", "tv"}:
        return []

    shortcode = parts[1]
    candidates = [
        ("instagram_reel_url", f"https://www.instagram.com/reel/{shortcode}/"),
        ("instagram_reels_url", f"https://www.instagram.com/reels/{shortcode}/"),
        ("instagram_post_url", f"https://www.instagram.com/p/{shortcode}/"),
        ("instagram_tv_url", f"https://www.instagram.com/tv/{shortcode}/"),
        ("instagram_reel_embed_url", f"https://www.instagram.com/reel/{shortcode}/embed/"),
        ("instagram_post_embed_url", f"https://www.instagram.com/p/{shortcode}/embed/"),
        ("instagram_tv_embed_url", f"https://www.instagram.com/tv/{shortcode}/embed/"),
    ]

    normalized_current = url.rstrip("/") + "/"
    seen = {normalized_current}
    fallbacks: list[tuple[str, str]] = []
    for name, candidate in candidates:
        if candidate not in seen:
            fallbacks.append((name, candidate))
            seen.add(candidate)
    return fallbacks


def is_instagram_share_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "instagram.com":
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0].lower() == "share" and parts[1].lower() in {"reel", "p", "tv"}:
        return True
    return len(parts) >= 2 and parts[0].lower() == "share"


def fetch_instagram_redirect_url(url: str, timeout_seconds: int, user_agent: str) -> str | None:
    if not is_instagram_share_url(url):
        return None

    headers = {"User-Agent": user_agent}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()

    redirect_url = str(response.url).split("?", 1)[0].split("#", 1)[0].rstrip("/") + "/"
    if provider_host(redirect_url) == "instagram.com" and not is_instagram_share_url(redirect_url):
        return redirect_url
    return None


def is_tiktok_short_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return False
    if host in {"vm.tiktok.com", "vt.tiktok.com"}:
        return True
    return host in {"tiktok.com", "m.tiktok.com"} and parts[0].lower() in {"t", "v"}


def fetch_tiktok_redirect_url(url: str, timeout_seconds: int, user_agent: str) -> str | None:
    if not is_tiktok_short_url(url):
        return None

    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()

    redirect_url = str(response.url).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if provider_host(redirect_url) in {"tiktok.com", "m.tiktok.com"} and not is_tiktok_short_url(redirect_url):
        return redirect_url
    return None


def download_tiktok_public_media(
    url: str,
    output_dir: Path,
    settings: Settings,
    user_agent: str,
) -> TikTokPublicDownloadResult:
    candidate_urls = tiktok_public_page_urls(
        url,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=user_agent,
    )
    attempt_errors: list[tuple[str, str]] = []
    headers = tiktok_public_headers(user_agent)

    output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
        for page_name, page_url in candidate_urls:
            try:
                response = client.get(page_url)
                response.raise_for_status()
                media_urls = extract_tiktok_public_media_urls(response.text)
                title = extract_html_meta_content(response.text, ("og:title", "twitter:title"))
                if not media_urls:
                    raise DownloadFailedError("TikTok public page did not expose a direct video URL", step="download")

                media_url = media_urls[0]
                public_id = tiktok_public_id(page_url)
                file_path = unique_output_path(output_dir / tiktok_public_filename(page_url, media_url))
                download_direct_media(
                    client,
                    media_url,
                    file_path,
                    max_bytes=settings.max_video_size_mb * 1024 * 1024,
                    headers={
                        "User-Agent": user_agent,
                        "Referer": page_url,
                    },
                )
                return TikTokPublicDownloadResult(
                    file_path=file_path,
                    info={
                        "id": public_id,
                        "title": title or f"TikTok video {public_id}",
                        "webpage_url": url,
                        "extractor": "tiktok_public",
                        "format_note": page_name,
                    },
                )
            except Exception as exc:
                attempt_errors.append((page_name, public_error_message(exc)))

    raise DownloadFailedError(
        f"TikTok public media fallback attempts failed: {summarize_attempt_errors(attempt_errors)}",
        step="download",
    )


def tiktok_public_page_urls(url: str, timeout_seconds: int, user_agent: str) -> list[tuple[str, str]]:
    page_urls: list[tuple[str, str]] = [("tiktok_public_original_url", url)]
    resolved_url: str | None = None

    if is_tiktok_short_url(url):
        try:
            resolved_url = fetch_tiktok_redirect_url(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
            if resolved_url:
                page_urls.insert(0, ("tiktok_public_short_redirect_url", resolved_url))
        except Exception as exc:
            logger.warning("tiktok_public_short_redirect_failed", extra={"url": url, "error": public_error_message(exc)})

    video_id = tiktok_public_id(resolved_url or url)
    if video_id != "tiktok_media":
        page_urls.append(("tiktok_public_embed_url", f"https://www.tiktok.com/embed/{quote(video_id, safe='')}"))

    return dedupe_named_urls(page_urls)


def tiktok_public_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.tiktok.com/",
    }


def extract_tiktok_public_media_urls(webpage: str) -> list[str]:
    candidates: list[str] = []
    for data in extract_tiktok_public_json_blocks(webpage):
        collect_tiktok_video_urls(data, candidates)

    direct_url_pattern = escaped_direct_media_url_pattern(
        r'(?:\.mp4|/video/tos/|mime_type=video_mp4|\\u002[fF]video\\u002[fF]tos\\u002[fF])'
    )
    candidates.extend(match.group(0) for match in re.finditer(direct_url_pattern, webpage))

    media_urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        decoded = decode_tiktok_public_media_url(candidate)
        if not decoded or decoded in seen or not looks_like_tiktok_video_url(decoded):
            continue
        seen.add(decoded)
        media_urls.append(decoded)
    return media_urls


def extract_tiktok_public_json_blocks(webpage: str) -> list[Any]:
    blocks: list[Any] = []
    pattern = r'<script[^>]+\bid=["\'](?:SIGI_STATE|sigi-persisted-data|__UNIVERSAL_DATA_FOR_REHYDRATION__)["\'][^>]*>(.*?)</script>'
    for match in re.finditer(pattern, webpage, flags=re.IGNORECASE | re.DOTALL):
        text = html.unescape(match.group(1)).strip()
        if not text:
            continue
        try:
            blocks.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return blocks


def collect_tiktok_video_urls(value: Any, candidates: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if normalized_key in {
                "playaddr",
                "downloadaddr",
                "playaddrh264",
                "playaddrbytevc1",
                "playaddrbytevc2",
            }:
                collect_tiktok_url_values(item, candidates)
            else:
                collect_tiktok_video_urls(item, candidates)
    elif isinstance(value, list):
        for item in value:
            collect_tiktok_video_urls(item, candidates)


def collect_tiktok_url_values(value: Any, candidates: list[str]) -> None:
    if isinstance(value, str):
        candidates.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if normalized_key in {"src", "url", "urllist", "urls"}:
                collect_tiktok_url_values(item, candidates)
            elif isinstance(item, (dict, list)):
                collect_tiktok_url_values(item, candidates)
    elif isinstance(value, list):
        for item in value:
            collect_tiktok_url_values(item, candidates)


def decode_tiktok_public_media_url(value: str) -> str | None:
    text = html.unescape(value).strip().strip('"').strip("'")
    for _ in range(2):
        if "\\/" not in text and "\\u" not in text:
            break
        try:
            text = json.loads(f'"{text}"')
        except json.JSONDecodeError:
            text = text.replace("\\/", "/").replace("\\u0026", "&")
            break

    text = html.unescape(text).strip()
    if not text.startswith(("http://", "https://")):
        return None
    return text


def looks_like_tiktok_video_url(value: str) -> bool:
    lowered = value.lower()
    return any(
        needle in lowered
        for needle in (
            ".mp4",
            "/video/tos/",
            "mime_type=video",
            "tiktokcdn",
            "tiktokv",
            "byteoversea",
            "ibytedtos",
        )
    )


def tiktok_public_filename(source_url: str, media_url: str) -> str:
    extension = Path(urlsplit(media_url).path).suffix.lower()
    if extension not in {".mp4", ".mov", ".m4v", ".webm"}:
        extension = ".mp4"
    return f"{tiktok_public_id(source_url)}{extension}"


def tiktok_public_id(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0].startswith("@") and parts[1].lower() == "video":
        return safe_filename_id(clean_tiktok_video_id(parts[2]))
    if len(parts) >= 2 and parts[0].lower() == "embed":
        return safe_filename_id(clean_tiktok_video_id(parts[1]))
    if host in {"vm.tiktok.com", "vt.tiktok.com"} and parts:
        return safe_filename_id(parts[0])
    if len(parts) >= 2 and parts[0].lower() in {"t", "v"}:
        return safe_filename_id(clean_tiktok_video_id(parts[1]))
    if len(parts) >= 3 and parts[0].lower() == "share" and parts[1].lower() == "video":
        return safe_filename_id(clean_tiktok_video_id(parts[2]))
    return "tiktok_media"


def clean_tiktok_video_id(value: str) -> str:
    return re.sub(r"\.html\Z", "", value, flags=re.IGNORECASE)


def download_instagram_public_media(
    url: str,
    output_dir: Path,
    settings: Settings,
    user_agent: str,
) -> InstagramPublicDownloadResult:
    candidate_urls = instagram_public_page_urls(
        url,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=user_agent,
    )
    attempt_errors: list[tuple[str, str]] = []
    headers = instagram_public_headers(user_agent)

    output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
        for page_name, page_url in candidate_urls:
            try:
                response = client.get(page_url)
                response.raise_for_status()
                media_urls = extract_instagram_public_media_urls(response.text)
                title = extract_html_meta_content(response.text, ("og:title", "twitter:title"))
                if not media_urls:
                    raise DownloadFailedError("Instagram public page did not expose a direct video URL", step="download")

                media_url = media_urls[0]
                file_path = unique_output_path(output_dir / instagram_public_filename(url, media_url))
                download_direct_media(
                    client,
                    media_url,
                    file_path,
                    max_bytes=settings.max_video_size_mb * 1024 * 1024,
                    headers={
                        "User-Agent": user_agent,
                        "Referer": page_url,
                    },
                )
                return InstagramPublicDownloadResult(
                    file_path=file_path,
                    info={
                        "id": instagram_public_id(url),
                        "title": title or f"Instagram video {instagram_public_id(url)}",
                        "webpage_url": url,
                        "extractor": "instagram_public",
                        "format_note": page_name,
                    },
                )
            except Exception as exc:
                attempt_errors.append((page_name, public_error_message(exc)))

    raise DownloadFailedError(
        f"Instagram public media fallback attempts failed: {summarize_attempt_errors(attempt_errors)}",
        step="download",
    )


def instagram_public_page_urls(url: str, timeout_seconds: int, user_agent: str) -> list[tuple[str, str]]:
    page_urls: list[tuple[str, str]] = [("instagram_public_original_url", url)]
    if is_instagram_share_url(url):
        try:
            redirect_url = fetch_instagram_redirect_url(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
            if redirect_url:
                page_urls.extend(
                    [
                        ("instagram_public_share_redirect_url", redirect_url),
                        *[
                            (f"instagram_public_{name}", fallback_url)
                            for name, fallback_url in instagram_fallback_urls(redirect_url)
                        ],
                    ]
                )
        except Exception as exc:
            logger.warning("instagram_public_share_redirect_failed", extra={"url": url, "error": public_error_message(exc)})

    page_urls.extend((f"instagram_public_{name}", fallback_url) for name, fallback_url in instagram_fallback_urls(url))
    return dedupe_named_urls(page_urls)


def instagram_public_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.instagram.com/",
    }


def extract_instagram_public_media_urls(webpage: str) -> list[str]:
    candidates: list[str] = []
    for meta_name in ("og:video", "og:video:secure_url", "twitter:player:stream"):
        if meta_content := extract_html_meta_content(webpage, (meta_name,)):
            candidates.append(meta_content)

    patterns = (
        r'"video_url"\s*:\s*"([^"]+)"',
        r'&quot;video_url&quot;\s*:\s*&quot;([^&]+)&quot;',
        r'"video_versions"\s*:\s*\[[^\]]*?"url"\s*:\s*"([^"]+)"',
        r'&quot;video_versions&quot;\s*:\s*\[[^\]]*?&quot;url&quot;\s*:\s*&quot;([^&]+)&quot;',
    )
    for pattern in patterns:
        candidates.extend(match.group(1) for match in re.finditer(pattern, webpage))

    direct_url_pattern = escaped_direct_media_url_pattern(r"\.mp4")
    candidates.extend(match.group(0) for match in re.finditer(direct_url_pattern, webpage))

    media_urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        decoded = decode_instagram_public_media_url(candidate)
        if not decoded or decoded in seen:
            continue
        seen.add(decoded)
        media_urls.append(decoded)
    return media_urls


def extract_html_meta_content(webpage: str, names: tuple[str, ...]) -> str | None:
    joined_names = "|".join(re.escape(name) for name in names)
    patterns = (
        rf'<meta\b(?=[^>]*(?:property|name)=["\'](?:{joined_names})["\'])(?=[^>]*content=["\']([^"\']+)["\'])[^>]*>',
        rf'<meta\b(?=[^>]*content=["\']([^"\']+)["\'])(?=[^>]*(?:property|name)=["\'](?:{joined_names})["\'])[^>]*>',
    )
    for pattern in patterns:
        match = re.search(pattern, webpage, flags=re.IGNORECASE)
        if match:
            value = html.unescape(match.group(1)).strip()
            if value:
                return value
    return None


def decode_instagram_public_media_url(value: str) -> str | None:
    text = html.unescape(value).strip().strip('"').strip("'")
    for _ in range(2):
        if "\\/" not in text and "\\u" not in text:
            break
        try:
            text = json.loads(f'"{text}"')
        except json.JSONDecodeError:
            text = text.replace("\\/", "/").replace("\\u0026", "&")
            break

    text = html.unescape(text).strip()
    if not text.startswith(("http://", "https://")):
        return None
    return text


def escaped_direct_media_url_pattern(required_fragment_pattern: str) -> str:
    prefix = r'https?(?::|\\u003[aA])(?:\\?/\\?/|\\u002[fF]\\u002[fF])'
    return rf'{prefix}[^"\'<>\s]+?{required_fragment_pattern}[^"\'<>\s]*'


def download_direct_media(
    client: httpx.Client,
    media_url: str,
    file_path: Path,
    max_bytes: int,
    headers: dict[str, str],
) -> None:
    total_bytes = 0
    try:
        with client.stream("GET", media_url, headers=headers) as response:
            response.raise_for_status()
            with file_path.open("wb") as output_file:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise DownloadFailedError("Direct media download exceeded MAX_VIDEO_SIZE_MB", step="download")
                    output_file.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    if not file_path.exists() or file_path.stat().st_size == 0:
        file_path.unlink(missing_ok=True)
        raise DownloadFailedError("Direct media response was empty", step="download")


def instagram_public_filename(source_url: str, media_url: str) -> str:
    extension = Path(urlsplit(media_url).path).suffix.lower()
    if extension not in {".mp4", ".mov", ".m4v", ".webm"}:
        extension = ".mp4"
    return f"{instagram_public_id(source_url)}{extension}"


def instagram_public_id(url: str) -> str:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() in {"reel", "reels", "p", "tv"}:
        return safe_filename_id(parts[1])
    if len(parts) >= 3 and parts[0].lower() == "share":
        return safe_filename_id(parts[2])
    if len(parts) >= 2 and parts[0].lower() == "share":
        return safe_filename_id(parts[1])
    return "instagram_media"


def safe_filename_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned[:80] or "instagram_media"


def x_fallback_urls(url: str) -> list[tuple[str, str]]:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return []

    parts = [part for part in parsed.path.split("/") if part]
    status_index = next((index for index, part in enumerate(parts) if part.lower() in {"status", "statuses"}), None)
    if status_index is None or len(parts) <= status_index + 1:
        return []

    status_id = parts[status_index + 1]
    if status_index >= 2 and parts[status_index - 2].lower() == "i" and parts[status_index - 1].lower() == "web":
        username = "i"
    elif status_index > 0 and parts[status_index - 1].lower() != "i":
        username = parts[status_index - 1]
    else:
        username = "i"

    quoted_status_id = quote(status_id, safe="")
    quoted_username = quote(username, safe="")
    candidates = [
        ("twitter_status_url", f"https://twitter.com/{quoted_username}/status/{quoted_status_id}"),
        ("x_i_web_status_url", f"https://x.com/i/web/status/{quoted_status_id}"),
        ("twitter_i_web_status_url", f"https://twitter.com/i/web/status/{quoted_status_id}"),
        ("twitter_statuses_url", f"https://twitter.com/statuses/{quoted_status_id}"),
    ]

    normalized_current = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return [
        (name, candidate)
        for name, candidate in dedupe_named_urls(candidates)
        if candidate.rstrip("/") != normalized_current
    ]


def dedupe_named_urls(named_urls: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for name, url in named_urls:
        normalized_url = url.rstrip("/")
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        deduped.append((name, url))
    return deduped


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
    if any(
        needle in lowered
        for needle in (
            "this video is private",
            "private video",
            "members-only",
            "join this channel",
            "has been removed",
            "does not exist",
            "copyright",
            "not available in your country",
            "rental",
            "purchase",
        )
    ):
        return False
    if any(
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
    ):
        return True
    return any(
        needle in lowered
        for needle in (
            "http error 5",
            "service unavailable",
            "temporarily unavailable",
            "unable to extract",
            "unable to download",
            "incomplete data",
            "player response",
            "streaming data",
        )
    )


def should_retry_tiktok_with_mobile_api(url: str, error_message: str) -> bool:
    if provider_host(url) not in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
        return False

    lowered = error_message.lower()
    if any(needle in lowered for needle in ("private", "log into an account that has access", "permission to view")):
        return False
    return True


def should_retry_instagram_with_url_variants(url: str, error_message: str) -> bool:
    if provider_host(url) != "instagram.com":
        return False

    lowered = error_message.lower()
    if any(
        needle in lowered
        for needle in (
            "only available for registered users who follow",
            "not authorized to view",
            "permission to view",
            "private",
        )
    ):
        return False
    return True


def should_retry_x_with_api_fallbacks(url: str, _error_message: str) -> bool:
    return provider_host(url) in {"x.com", "twitter.com", "mobile.twitter.com"}


def download_failure_guidance(url: str, settings: Settings) -> dict[str, str | list[str]]:
    host = provider_host(url)

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        next_steps = [
            "Built-in YouTube no-auth yt-dlp, PO-token provider, client, Visitor Data, and public mirror/Cobalt hooks have been exhausted for this request.",
        ]
        if not (settings.youtube_piped_api_base_urls or settings.youtube_invidious_base_urls):
            next_steps.append("Configure your own Piped or Invidious API instance with YOUTUBE_PIPED_API_BASE_URLS or YOUTUBE_INVIDIOUS_BASE_URLS for another no-cookie YouTube path.")
        if not settings.cobalt_api_base_url:
            next_steps.append("Configure a trusted Cobalt API instance with COBALT_API_BASE_URL as a server-side no-auth fallback.")
        if not settings.social_download_proxy_url:
            next_steps.append("Use SOCIAL_DOWNLOAD_PROXY_URL with infrastructure you operate or are allowed to use if Cloud Run egress is being blocked.")
        if not settings.enable_auth_cookies:
            next_steps.append("If the video is login-only or YouTube hard-blocks anonymous server traffic, the remaining reliable fallback is intentionally enabling cookies with ENABLE_AUTH_COOKIES=true.")
        return {
            "category": "youtube_anonymous_exhausted",
            "next_steps": next_steps,
        }

    if host in {"instagram.com"}:
        next_steps = [
            "Built-in Instagram no-auth yt-dlp URL variants, share redirects, embed URLs, and public direct-media HTML parsing have been exhausted for this request.",
        ]
        if not settings.cobalt_api_base_url:
            next_steps.append("Configure a trusted Cobalt API instance with COBALT_API_BASE_URL for another server-side no-auth attempt.")
        if not settings.social_download_proxy_url:
            next_steps.append("Use SOCIAL_DOWNLOAD_PROXY_URL with allowed infrastructure if Instagram is blocking Cloud Run egress.")
        if not settings.enable_auth_cookies:
            next_steps.append("If the Reel is private, follower-only, expired, or login-gated, anonymous download cannot be made reliable; cookies or a direct file upload are the remaining reliable options.")
        return {
            "category": "instagram_anonymous_exhausted",
            "next_steps": next_steps,
        }

    if host in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
        next_steps = [
            "Built-in TikTok no-auth yt-dlp, short-link resolution, mobile API profiles, and public direct-media HTML parsing have been exhausted for this request.",
        ]
        if not settings.cobalt_api_base_url:
            next_steps.append("Configure a trusted Cobalt API instance with COBALT_API_BASE_URL for another server-side no-auth attempt.")
        if not settings.social_download_proxy_url:
            next_steps.append("Use SOCIAL_DOWNLOAD_PROXY_URL with allowed infrastructure if TikTok is blocking Cloud Run egress.")
        if not settings.enable_auth_cookies:
            next_steps.append("If TikTok returns a login/challenge page or region block, anonymous download may not be reliable; cookies, alternate egress, or direct file upload are the remaining reliable options.")
        return {
            "category": "tiktok_anonymous_exhausted",
            "next_steps": next_steps,
        }

    if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
        next_steps = [
            "Built-in X/Twitter no-auth yt-dlp URL variants and legacy API fallback have been exhausted for this request.",
        ]
        if not settings.cobalt_api_base_url:
            next_steps.append("Configure a trusted Cobalt API instance with COBALT_API_BASE_URL for another server-side no-auth attempt.")
        if not settings.social_download_proxy_url:
            next_steps.append("Use SOCIAL_DOWNLOAD_PROXY_URL with allowed infrastructure if X/Twitter is blocking Cloud Run egress.")
        if not settings.enable_auth_cookies:
            next_steps.append("If the post or media is login-gated, cookies or direct file upload are the remaining reliable options.")
        return {
            "category": "x_anonymous_exhausted",
            "next_steps": next_steps,
        }

    return {
        "category": "provider_anonymous_exhausted",
        "next_steps": [
            "The configured anonymous downloader paths were exhausted for this provider.",
            "Use a supported public URL, configure an allowed proxy/Cobalt fallback, or provide the media file directly.",
        ],
    }


def format_download_failure_guidance(guidance: dict[str, str | list[str]]) -> str:
    next_steps = [str(step) for step in guidance.get("next_steps") or [] if str(step).strip()]
    if not next_steps:
        return ""
    return " Next steps: " + " ".join(next_steps)


def should_try_cobalt_fallback(url: str) -> bool:
    return provider_host(url) in {
        "instagram.com",
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
        "x.com",
        "twitter.com",
        "mobile.twitter.com",
    }


def provider_host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")
