from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.downloader_service import DownloaderService, compact_yt_dlp_debug_log, downloader_runtime_info
from app.services.social_video_service import SocialVideoService
from app.services.task_queue_service import TASK_SECRET_HEADER
from app.utils.errors import public_error_message

router = APIRouter(tags=["diagnostics"])


class DownloadDiagnosticPayload(BaseModel):
    url: str = Field(min_length=1)
    include_debug_log: bool = False
    debug_log_max_chars: int = Field(default=20000, ge=1000, le=80000)


class NormalizeDiagnosticPayload(BaseModel):
    url: str = Field(min_length=1)


def require_task_secret(
    x_reelvault_task_secret: str | None,
    settings: Settings,
) -> None:
    if not settings.task_request_secret:
        raise HTTPException(status_code=500, detail="TASK_REQUEST_SECRET is not configured")
    if x_reelvault_task_secret != settings.task_request_secret:
        raise HTTPException(status_code=401, detail="Invalid task secret")


@router.post("/diagnostics/download")
def download_diagnostic(
    payload: DownloadDiagnosticPayload,
    x_reelvault_task_secret: str | None = Header(default=None, alias=TASK_SECRET_HEADER),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    require_task_secret(x_reelvault_task_secret, settings)

    reel = SocialVideoService.normalize_url(payload.url)
    if not reel:
        raise HTTPException(status_code=400, detail="Unsupported social video URL")

    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="diagnostic-", dir=settings.temp_dir) as temp_dir:
        output_dir = Path(temp_dir)
        debug_log: list[str] | None = [] if payload.include_debug_log else None
        try:
            result = DownloaderService(settings, yt_dlp_debug_log=debug_log).download(reel.url, output_dir)
        except Exception as exc:
            response = {
                "ok": False,
                "provider": reel.provider,
                "url": reel.url,
                "raw_url": payload.url,
                "status": "download_exception",
                "error": public_error_message(exc),
                "downloader": downloader_runtime_info(settings),
            }
            append_debug_log(response, debug_log, payload.debug_log_max_chars)
            return response

        file_size_bytes = None
        if result.file_path and result.file_path.exists():
            file_size_bytes = result.file_path.stat().st_size

        response = {
            "ok": result.success,
            "provider": reel.provider,
            "url": reel.url,
            "raw_url": payload.url,
            "status": result.status,
            "title": result.title,
            "creator_username": result.creator_username,
            "file_size_bytes": file_size_bytes,
            "metadata": result.metadata,
            "error": result.error_message,
            "failure_category": result.failure_category,
            "next_steps": result.next_steps,
            "downloader": downloader_runtime_info(settings),
        }
        append_debug_log(response, debug_log, payload.debug_log_max_chars)
        return response


@router.post("/diagnostics/normalize")
def normalize_diagnostic(
    payload: NormalizeDiagnosticPayload,
    x_reelvault_task_secret: str | None = Header(default=None, alias=TASK_SECRET_HEADER),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    require_task_secret(x_reelvault_task_secret, settings)

    reel = SocialVideoService.normalize_url(payload.url)
    if not reel:
        raise HTTPException(status_code=400, detail="Unsupported social video URL")

    return {
        "ok": True,
        "provider": reel.provider,
        "url": reel.url,
        "raw_url": reel.raw_url,
        "shortcode": reel.shortcode,
        "is_share_url": reel.is_share_url,
        "downloader": downloader_runtime_info(settings),
    }


def append_debug_log(response: dict[str, object], debug_log: list[str] | None, max_chars: int) -> None:
    if debug_log is None:
        return
    response["yt_dlp_debug_log"] = compact_yt_dlp_debug_log(debug_log, max_chars=max_chars)
