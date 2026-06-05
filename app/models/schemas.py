from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProcessingStatus(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    QUEUE_FAILED = "queue_failed"
    PENDING_PILLAR_CONFIRMATION = "pending_pillar_confirmation"
    INVALID_URL = "invalid_url"
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_COMPLETE = "download_complete"
    DRIVE_UPLOAD_FAILED = "drive_upload_failed"
    DRIVE_UPLOAD_COMPLETE = "drive_upload_complete"
    TRANSCRIPTION_STARTED = "transcription_started"
    TRANSCRIPTION_FAILED = "transcription_failed"
    TRANSCRIPTION_COMPLETE = "transcription_complete"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_FAILED = "analysis_failed"
    COMPLETE = "complete"
    PARTIAL_COMPLETE = "partial_complete"
    CANCELLED = "cancelled"


class ContentPillar(str, Enum):
    GYM = "Gym"
    TECH = "Tech"
    MOTIVATION = "Motivation"
    MORNING_ROUTINE = "Morning Routine"
    JOB_SEARCH = "Job Search"
    FAITH = "Faith"


class ReelReference(BaseModel):
    url: str
    raw_url: str | None = None
    shortcode: str | None = None
    is_share_url: bool = False
    provider: str = "instagram"

    @property
    def source_type(self) -> str:
        if self.provider == "telegram":
            return "telegram_upload"
        return f"{self.provider}_url"


class TelegramMediaReference(BaseModel):
    file_id: str
    file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    media_type: str = "video"


class DownloadResult(BaseModel):
    success: bool
    status: str
    file_path: Path | None = None
    creator_username: str | None = None
    title: str | None = None
    error_message: str | None = None
    metadata: dict[str, str | int | float | None] = Field(default_factory=dict)


class DriveUploadResult(BaseModel):
    file_id: str
    name: str
    web_view_link: str | None = None
    web_content_link: str | None = None


class GoogleDocResult(BaseModel):
    document_id: str
    title: str
    web_view_link: str | None = None


class TranscriptionResult(BaseModel):
    text: str
    model: str
    audio_files: list[str]


class ProcessingTaskPayload(BaseModel):
    reel: ReelReference
    chat_id: int
    row_index: int
    initial_pillar: ContentPillar | None = None
    initial_pillar_source: str = ""
    telegram_media: TelegramMediaReference | None = None


class SheetUsedWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sheet_name: str = Field(alias="sheetName")
    row_number: int = Field(alias="rowNumber", ge=2)
    used: bool
    used_at: str = Field(default="", alias="usedAt")
    pillar: str = ""
    shortcode: str = ""
    reel_url: str = Field(default="", alias="reelUrl")
    inspiration_folder_link: str = Field(default="", alias="inspirationFolderLink")


class OriginalContentIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    angle: str
    sample_hook: str
    short_script_outline: list[str] = Field(min_length=3)

    @field_validator("title", "angle", "sample_hook")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be empty")
        return value


class ReelAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pillar: ContentPillar
    pillar_confidence: float = Field(ge=0, le=1)
    hook: str
    main_idea: str
    summary: str
    content_structure: list[str] = Field(min_length=3)
    why_it_works: list[str] = Field(min_length=3)
    target_audience: str
    tone: str
    original_content_ideas: list[OriginalContentIdea] = Field(min_length=3, max_length=3)
    caption_options: list[str] = Field(min_length=3, max_length=3)
    searchable_tags: list[str] = Field(min_length=5, max_length=5)
    script_title: str
    re_hooks: list[str] = Field(min_length=3, max_length=3)
    custom_script_lines: list[str] = Field(min_length=5)

    @field_validator("hook", "main_idea", "summary", "target_audience", "tone", "script_title")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("caption_options", "searchable_tags", "re_hooks", "custom_script_lines")
    @classmethod
    def required_text_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list items cannot be empty")
        return cleaned


SHEET_FIELDS = [
    ("Created At", "created_at"),
    ("Reel URL", "reel_url"),
    ("Shortcode", "shortcode"),
    ("Creator", "creator"),
    ("Status", "status"),
    ("Download Status", "download_status"),
    ("Transcription Status", "transcription_status"),
    ("Analysis Status", "analysis_status"),
    ("Drive Video Link", "drive_video_link"),
    ("Drive Audio Link", "drive_audio_link"),
    ("Transcript", "transcript"),
    ("Hook", "hook"),
    ("Summary", "summary"),
    ("Main Idea", "main_idea"),
    ("Content Structure", "content_structure"),
    ("Why It Works", "why_it_works"),
    ("Target Audience", "target_audience"),
    ("Tone", "tone"),
    ("Original Idea 1", "original_idea_1"),
    ("Original Idea 2", "original_idea_2"),
    ("Original Idea 3", "original_idea_3"),
    ("Caption 1", "caption_1"),
    ("Caption 2", "caption_2"),
    ("Caption 3", "caption_3"),
    ("Tags", "tags"),
    ("Error Message", "error_message"),
    ("Pillar", "pillar"),
    ("Pillar Source", "pillar_source"),
    ("Pillar Confidence", "pillar_confidence"),
    ("Script Title", "script_title"),
    ("Re-hooks", "re_hooks"),
    ("Custom Script", "custom_script"),
    ("Script Google Doc Link", "script_google_doc_link"),
    ("Used", "used"),
    ("Inspiration Folder Link", "inspiration_folder_link"),
    ("Source Type", "source_type"),
    ("Telegram File ID", "telegram_file_id"),
    ("Telegram File Unique ID", "telegram_file_unique_id"),
    ("Telegram File Name", "telegram_file_name"),
    ("Telegram MIME Type", "telegram_mime_type"),
    ("Telegram File Size", "telegram_file_size"),
    ("Used At", "used_at"),
]

SHEET_COLUMNS = [column for column, _field in SHEET_FIELDS]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def truncate_cell(value: str | None, limit: int = 45_000) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= limit:
        return value
    return value[: limit - 32] + "\n[truncated for Google Sheets]"


class SheetRow(BaseModel):
    created_at: str = Field(default_factory=utc_now_iso)
    reel_url: str
    shortcode: str = ""
    creator: str = ""
    status: str = ProcessingStatus.RECEIVED.value
    download_status: str = ""
    transcription_status: str = ""
    analysis_status: str = ""
    drive_video_link: str = ""
    drive_audio_link: str = ""
    transcript: str = ""
    hook: str = ""
    summary: str = ""
    main_idea: str = ""
    content_structure: str = ""
    why_it_works: str = ""
    target_audience: str = ""
    tone: str = ""
    original_idea_1: str = ""
    original_idea_2: str = ""
    original_idea_3: str = ""
    caption_1: str = ""
    caption_2: str = ""
    caption_3: str = ""
    tags: str = ""
    error_message: str = ""
    pillar: str = ""
    pillar_source: str = ""
    pillar_confidence: str = ""
    script_title: str = ""
    re_hooks: str = ""
    custom_script: str = ""
    script_google_doc_link: str = ""
    used: str = "FALSE"
    inspiration_folder_link: str = ""
    source_type: str = "instagram_url"
    telegram_file_id: str = ""
    telegram_file_unique_id: str = ""
    telegram_file_name: str = ""
    telegram_mime_type: str = ""
    telegram_file_size: str = ""
    used_at: str = ""

    @classmethod
    def from_reel(cls, reel: ReelReference) -> "SheetRow":
        return cls(reel_url=reel.url, shortcode=reel.shortcode or "", source_type=reel.source_type)

    @classmethod
    def from_telegram_media(cls, reel: ReelReference, media: TelegramMediaReference) -> "SheetRow":
        row = cls.from_reel(reel)
        row.apply_telegram_media(media)
        return row

    @classmethod
    def from_values(cls, values: list[str]) -> "SheetRow":
        mapped = {
            field_name: values[index] if index < len(values) else ""
            for index, (_column, field_name) in enumerate(SHEET_FIELDS)
        }
        if not mapped["reel_url"]:
            raise ValueError("Sheet row is missing Reel URL")
        return cls.model_validate(mapped)

    def apply_analysis(self, analysis: ReelAnalysis, preserve_existing_pillar: bool = False) -> None:
        if not preserve_existing_pillar:
            self.pillar = analysis.pillar.value
            self.pillar_source = self.pillar_source or "ai"
            self.pillar_confidence = f"{analysis.pillar_confidence:.2f}"
        elif not self.pillar_confidence:
            self.pillar_confidence = "1.00"

        self.hook = analysis.hook
        self.summary = analysis.summary
        self.main_idea = analysis.main_idea
        self.content_structure = "\n".join(analysis.content_structure)
        self.why_it_works = "\n".join(analysis.why_it_works)
        self.target_audience = analysis.target_audience
        self.tone = analysis.tone

        formatted_ideas = [format_idea_for_sheet(idea) for idea in analysis.original_content_ideas]
        self.original_idea_1 = formatted_ideas[0]
        self.original_idea_2 = formatted_ideas[1]
        self.original_idea_3 = formatted_ideas[2]

        self.caption_1 = analysis.caption_options[0]
        self.caption_2 = analysis.caption_options[1]
        self.caption_3 = analysis.caption_options[2]
        self.tags = ", ".join(analysis.searchable_tags)
        self.script_title = analysis.script_title
        self.re_hooks = "\n".join(analysis.re_hooks)
        self.custom_script = "\n".join(analysis.custom_script_lines)

    def apply_telegram_media(self, media: TelegramMediaReference) -> None:
        self.source_type = "telegram_upload"
        self.telegram_file_id = media.file_id
        self.telegram_file_unique_id = media.file_unique_id or ""
        self.telegram_file_name = media.file_name or ""
        self.telegram_mime_type = media.mime_type or ""
        self.telegram_file_size = str(media.file_size) if media.file_size is not None else ""

    def to_reel_reference(self) -> ReelReference:
        return ReelReference(
            url=self.reel_url,
            shortcode=self.shortcode or None,
            is_share_url="/share/reel/" in self.reel_url,
            provider=provider_from_source(self.source_type, self.reel_url),
        )

    def to_telegram_media_reference(self) -> TelegramMediaReference | None:
        if not self.telegram_file_id:
            return None
        return TelegramMediaReference(
            file_id=self.telegram_file_id,
            file_unique_id=self.telegram_file_unique_id or None,
            file_name=self.telegram_file_name or None,
            mime_type=self.telegram_mime_type or None,
            file_size=int(self.telegram_file_size) if self.telegram_file_size.isdigit() else None,
        )

    def append_error(self, message: str) -> None:
        clean_message = message.strip()
        if not clean_message:
            return
        if self.error_message:
            self.error_message = f"{self.error_message}\n{clean_message}"
        else:
            self.error_message = clean_message

    def apply_used_state(self, used: bool, used_at: str | None = None) -> None:
        self.used = "TRUE" if used else "FALSE"
        self.used_at = (used_at or utc_now_iso()) if used else ""

    def to_values(self) -> list[str]:
        values: list[str] = []
        for column, field_name in SHEET_FIELDS:
            value = getattr(self, field_name)
            if column == "Transcript":
                value = truncate_cell(value)
            elif column == "Error Message":
                value = truncate_cell(value, limit=10_000)
            elif column == "Custom Script":
                value = truncate_cell(value, limit=20_000)
            values.append(value)
        return values


def format_idea_for_sheet(idea: OriginalContentIdea) -> str:
    outline = "\n".join(f"- {line}" for line in idea.short_script_outline)
    return f"{idea.title}\nAngle: {idea.angle}\nHook: {idea.sample_hook}\nOutline:\n{outline}"


def provider_from_source(source_type: str, url: str) -> str:
    if source_type == "telegram_upload" or url.startswith("telegram-upload://"):
        return "telegram"
    if source_type.endswith("_url"):
        return source_type.removesuffix("_url") or "instagram"
    if "youtu.be" in url or "youtube.com" in url:
        return "youtube"
    if "tiktok.com" in url:
        return "tiktok"
    if "x.com" in url or "twitter.com" in url:
        return "x"
    return "instagram"
