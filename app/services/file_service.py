from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from app.config import Settings
from app.utils.errors import FileProcessingError, public_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)


class FileService:
    """Manage temporary files, FFmpeg audio extraction, compression, and cleanup."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)

    def create_job_dir(self, shortcode: str | None) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", shortcode or "reel").strip("_") or "reel"
        job_dir = self.settings.temp_dir / f"{safe_name}_{self._unique_suffix()}"
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def cleanup_dir(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
        except Exception as exc:
            logger.warning("temp_cleanup_failed", extra={"path": str(path), "error": public_error_message(exc)})

    def extract_audio_for_transcription(self, video_path: Path, job_dir: Path) -> list[Path]:
        if not video_path.exists():
            raise FileProcessingError(f"Video file does not exist: {video_path}", step="audio_extraction")

        primary_audio = job_dir / "audio_64k.mp3"
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(primary_audio),
            ],
            step="audio_extraction",
        )

        if self.file_size_mb(primary_audio) <= self.settings.max_audio_size_mb:
            return [primary_audio]

        compressed_audio = job_dir / "audio_32k.mp3"
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(primary_audio),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                str(compressed_audio),
            ],
            step="audio_compression",
        )

        if self.file_size_mb(compressed_audio) <= self.settings.max_audio_size_mb:
            return [compressed_audio]

        return self._split_audio(compressed_audio, job_dir)

    def file_size_mb(self, file_path: Path) -> float:
        return file_path.stat().st_size / (1024 * 1024)

    def _split_audio(self, audio_path: Path, job_dir: Path) -> list[Path]:
        chunk_dir = job_dir / "audio_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_pattern = chunk_dir / "chunk_%03d.mp3"
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(audio_path),
                "-f",
                "segment",
                "-segment_time",
                "600",
                "-c",
                "copy",
                str(chunk_pattern),
            ],
            step="audio_split",
        )
        chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
        if not chunks:
            raise FileProcessingError("Audio split produced no chunks", step="audio_split")
        oversized_chunks = [
            chunk.name for chunk in chunks if self.file_size_mb(chunk) > self.settings.max_audio_size_mb
        ]
        if oversized_chunks:
            raise FileProcessingError(
                "Audio chunks still exceed MAX_AUDIO_SIZE_MB: " + ", ".join(oversized_chunks),
                step="audio_split",
            )
        return chunks

    def _run_ffmpeg(self, command: list[str], step: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise FileProcessingError("FFmpeg is not installed or not on PATH", step=step) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise FileProcessingError(f"FFmpeg failed during {step}: {detail}", step=step) from exc

    def _unique_suffix(self) -> str:
        import uuid

        return uuid.uuid4().hex[:10]

