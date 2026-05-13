from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from app.config import Settings
from app.models.schemas import TranscriptionResult
from app.utils.errors import ExternalServiceError, public_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)


class TranscriptionService:
    """OpenAI speech-to-text wrapper for one or more audio chunks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def transcribe_files(self, audio_files: list[Path]) -> TranscriptionResult:
        if not self.client:
            raise ExternalServiceError("OPENAI_API_KEY is not configured", step="transcription")
        if not audio_files:
            raise ExternalServiceError("No audio files supplied for transcription", step="transcription")

        transcripts: list[str] = []
        for index, audio_path in enumerate(audio_files, start=1):
            try:
                transcripts.append(self._transcribe_one(audio_path))
            except Exception as exc:
                logger.warning(
                    "openai_transcription_failed",
                    extra={"audio_file": audio_path.name, "error": public_error_message(exc)},
                )
                raise ExternalServiceError(
                    f"OpenAI transcription failed for chunk {index}: {public_error_message(exc)}",
                    step="transcription",
                ) from exc

        return TranscriptionResult(
            text="\n\n".join(part.strip() for part in transcripts if part.strip()),
            model=self.settings.openai_transcription_model,
            audio_files=[str(path) for path in audio_files],
        )

    def _transcribe_one(self, audio_path: Path) -> str:
        if not audio_path.exists():
            raise ExternalServiceError(f"Audio file does not exist: {audio_path}", step="transcription")
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        if size_mb > self.settings.max_audio_size_mb:
            raise ExternalServiceError(
                f"Audio file exceeds MAX_AUDIO_SIZE_MB ({size_mb:.1f} MB)",
                step="transcription",
            )

        with audio_path.open("rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                model=self.settings.openai_transcription_model,
                file=audio_file,
            )
        text = getattr(result, "text", None)
        if not text and isinstance(result, dict):
            text = result.get("text")
        if not text:
            raise ExternalServiceError("OpenAI transcription returned empty text", step="transcription")
        return str(text)

