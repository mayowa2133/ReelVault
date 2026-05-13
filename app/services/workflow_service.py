from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.models.schemas import ContentPillar, ProcessingStatus, ReelReference, SheetRow
from app.services.analysis_service import AnalysisService
from app.services.downloader_service import DownloaderService
from app.services.file_service import FileService
from app.services.google_docs_service import GoogleDocsService
from app.services.google_drive_service import GoogleDriveService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.telegram_service import TelegramService
from app.services.transcription_service import TranscriptionService
from app.utils.errors import public_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)


def process_reel_inspiration(
    reel: ReelReference,
    chat_id: int,
    settings: Settings,
    initial_pillar: ContentPillar | None = None,
    initial_pillar_source: str = "",
    existing_row_index: int | None = None,
) -> None:
    """Run the full Reel processing workflow in a FastAPI background task."""

    row = SheetRow.from_reel(reel)
    if initial_pillar:
        row.pillar = initial_pillar.value
        row.pillar_source = initial_pillar_source
        row.pillar_confidence = "1.00"
    elif initial_pillar_source:
        row.pillar_source = initial_pillar_source

    telegram = TelegramService(settings)
    sheets = GoogleSheetsService(settings)
    drive = GoogleDriveService(settings)
    docs = GoogleDocsService(settings)
    files = FileService(settings)
    downloader = DownloaderService(settings)
    transcriber = TranscriptionService(settings)
    analyzer = AnalysisService(settings)

    job_dir = files.create_job_dir(reel.shortcode)
    row_index: int | None = existing_row_index
    uploaded_video_file_id: str | None = None
    uploaded_audio_file_ids: list[str] = []

    def update_sheet() -> None:
        if row_index is None:
            return
        try:
            sheets.update_row(row_index, row)
        except Exception as exc:
            logger.warning(
                "google_sheets_update_failed",
                extra={"row_index": row_index, "error": public_error_message(exc)},
            )

    def mark(
        *,
        status: ProcessingStatus | None = None,
        download_status: ProcessingStatus | str | None = None,
        transcription_status: ProcessingStatus | str | None = None,
        analysis_status: ProcessingStatus | str | None = None,
        error: str | None = None,
    ) -> None:
        if status:
            row.status = status.value
        if download_status:
            row.download_status = download_status.value if isinstance(download_status, ProcessingStatus) else download_status
        if transcription_status:
            row.transcription_status = (
                transcription_status.value if isinstance(transcription_status, ProcessingStatus) else transcription_status
            )
        if analysis_status:
            row.analysis_status = analysis_status.value if isinstance(analysis_status, ProcessingStatus) else analysis_status
        if error:
            row.append_error(error)
        update_sheet()

    try:
        try:
            if row_index is None:
                row_index = sheets.append_row(row)
            else:
                row = sheets.get_row(row_index)
                if initial_pillar:
                    row.pillar = initial_pillar.value
                    row.pillar_source = initial_pillar_source
                    row.pillar_confidence = "1.00"
                elif initial_pillar_source:
                    row.pillar = ""
                    row.pillar_source = initial_pillar_source
                    row.pillar_confidence = ""
                update_sheet()
        except Exception as exc:
            row.append_error(f"Google Sheets append failed: {public_error_message(exc)}")
            logger.warning("google_sheets_append_failed", extra={"error": public_error_message(exc)})

        mark(status=ProcessingStatus.DOWNLOAD_STARTED, download_status=ProcessingStatus.DOWNLOAD_STARTED)
        download_result = downloader.download(reel.url, job_dir)
        if download_result.creator_username:
            row.creator = download_result.creator_username

        if not download_result.success or not download_result.file_path:
            mark(
                status=ProcessingStatus.PARTIAL_COMPLETE,
                download_status=ProcessingStatus.DOWNLOAD_FAILED,
                error=download_result.error_message or "Download failed; manual review needed.",
            )
            send_final_message(telegram, chat_id, row, sheets.sheet_url)
            return

        video_path = download_result.file_path
        mark(status=ProcessingStatus.DOWNLOAD_COMPLETE, download_status=ProcessingStatus.DOWNLOAD_COMPLETE)

        uploaded_video_file_id = upload_video_if_possible(drive, row, video_path, update_sheet)

        try:
            audio_files = files.extract_audio_for_transcription(video_path, job_dir)
        except Exception as exc:
            mark(
                status=ProcessingStatus.PARTIAL_COMPLETE,
                transcription_status=ProcessingStatus.TRANSCRIPTION_FAILED,
                error=f"Audio extraction failed: {public_error_message(exc)}",
            )
            send_final_message(telegram, chat_id, row, sheets.sheet_url)
            return

        uploaded_audio_file_ids = upload_audio_if_possible(settings, drive, row, audio_files, update_sheet)

        mark(
            status=ProcessingStatus.TRANSCRIPTION_STARTED,
            transcription_status=ProcessingStatus.TRANSCRIPTION_STARTED,
        )
        try:
            transcription = transcriber.transcribe_files(audio_files)
            row.transcript = transcription.text
            mark(
                status=ProcessingStatus.TRANSCRIPTION_COMPLETE,
                transcription_status=ProcessingStatus.TRANSCRIPTION_COMPLETE,
            )
        except Exception as exc:
            mark(
                status=ProcessingStatus.PARTIAL_COMPLETE,
                transcription_status=ProcessingStatus.TRANSCRIPTION_FAILED,
                error=public_error_message(exc),
            )
            send_final_message(telegram, chat_id, row, sheets.sheet_url)
            return

        mark(status=ProcessingStatus.ANALYSIS_STARTED, analysis_status=ProcessingStatus.ANALYSIS_STARTED)
        try:
            selected_pillar = ContentPillar(row.pillar) if row.pillar else None
            analysis = analyzer.analyze(row.transcript, reel.url, row.creator or None, selected_pillar)
            row.apply_analysis(analysis, preserve_existing_pillar=selected_pillar is not None)
            inspiration_folder_id = organize_drive_files_if_possible(
                drive,
                row,
                [file_id for file_id in [uploaded_video_file_id, *uploaded_audio_file_ids] if file_id],
                update_sheet,
            )
            create_script_doc_if_possible(docs, row, update_sheet, inspiration_folder_id)
            final_status = ProcessingStatus.PARTIAL_COMPLETE if row.error_message else ProcessingStatus.COMPLETE
            row.status = final_status.value
            row.analysis_status = ProcessingStatus.COMPLETE.value
            append_pillar_sheet_row_if_possible(sheets, row, update_sheet)
            update_sheet()
        except Exception as exc:
            mark(
                status=ProcessingStatus.PARTIAL_COMPLETE,
                analysis_status=ProcessingStatus.ANALYSIS_FAILED,
                error=public_error_message(exc),
            )

        send_final_message(telegram, chat_id, row, sheets.sheet_url)
    except Exception as exc:
        row.append_error(public_error_message(exc))
        row.status = ProcessingStatus.PARTIAL_COMPLETE.value
        update_sheet()
        logger.exception("reel_workflow_failed", extra={"shortcode": reel.shortcode, "error": public_error_message(exc)})
        send_final_message(telegram, chat_id, row, sheets.sheet_url)
    finally:
        files.cleanup_dir(job_dir)


def upload_video_if_possible(
    drive: GoogleDriveService,
    row: SheetRow,
    video_path: Path,
    update_sheet,
) -> str | None:
    try:
        folder_id = pillar_folder_id_if_possible(drive, row, update_sheet)
        upload = drive.upload_file(
            video_path,
            description=f"Private Reel inspiration reference: {row.reel_url}",
            folder_id=folder_id,
        )
        row.drive_video_link = upload.web_view_link or ""
        row.status = ProcessingStatus.DRIVE_UPLOAD_COMPLETE.value
        return upload.file_id
    except Exception as exc:
        row.status = ProcessingStatus.DRIVE_UPLOAD_FAILED.value
        row.append_error(f"Google Drive video upload failed: {public_error_message(exc)}")
        return None
    finally:
        update_sheet()


def upload_audio_if_possible(
    settings: Settings,
    drive: GoogleDriveService,
    row: SheetRow,
    audio_files: list[Path],
    update_sheet,
) -> list[str]:
    if not settings.enable_audio_upload or not audio_files:
        return []
    try:
        links: list[str] = []
        file_ids: list[str] = []
        folder_id = pillar_folder_id_if_possible(drive, row, update_sheet)
        for audio_path in audio_files:
            upload = drive.upload_file(
                audio_path,
                description=f"Private Reel inspiration audio: {row.reel_url}",
                folder_id=folder_id,
            )
            if upload.web_view_link:
                links.append(upload.web_view_link)
            file_ids.append(upload.file_id)
        row.drive_audio_link = "\n".join(links)
        return file_ids
    except Exception as exc:
        row.append_error(f"Google Drive audio upload failed: {public_error_message(exc)}")
        return []
    finally:
        update_sheet()


def create_script_doc_if_possible(
    docs: GoogleDocsService,
    row: SheetRow,
    update_sheet,
    folder_id: str | None = None,
) -> None:
    try:
        document = docs.create_script_doc(row, folder_id=folder_id)
        row.script_google_doc_link = document.web_view_link or ""
    except Exception as exc:
        row.append_error(f"Google Docs script creation failed: {public_error_message(exc)}")
    update_sheet()


def pillar_folder_id_if_possible(
    drive: GoogleDriveService,
    row: SheetRow,
    update_sheet,
) -> str | None:
    if not row.pillar:
        return None
    try:
        return drive.get_or_create_pillar_folder(row.pillar)
    except Exception as exc:
        row.append_error(f"Google Drive pillar folder failed: {public_error_message(exc)}")
        update_sheet()
        return None


def organize_drive_files_if_possible(
    drive: GoogleDriveService,
    row: SheetRow,
    file_ids: list[str],
    update_sheet,
) -> str | None:
    folder_id = inspiration_folder_id_if_possible(drive, row, update_sheet)
    if not folder_id:
        return None
    for file_id in file_ids:
        try:
            drive.move_file_to_folder(file_id, folder_id)
        except Exception as exc:
            row.append_error(f"Google Drive file organization failed: {public_error_message(exc)}")
            update_sheet()
    return folder_id


def inspiration_folder_id_if_possible(
    drive: GoogleDriveService,
    row: SheetRow,
    update_sheet,
) -> str | None:
    if not row.pillar:
        return None
    try:
        folder = drive.get_or_create_inspiration_folder(
            row.pillar,
            title=row.script_title or row.hook or row.shortcode or "Reel Inspiration",
            shortcode=row.shortcode or None,
        )
        row.inspiration_folder_link = folder.web_view_link
        update_sheet()
        return folder.folder_id
    except Exception as exc:
        row.append_error(f"Google Drive inspiration folder failed: {public_error_message(exc)}")
        update_sheet()
        return None


def append_pillar_sheet_row_if_possible(
    sheets: GoogleSheetsService,
    row: SheetRow,
    update_sheet,
) -> None:
    if not row.pillar:
        return
    try:
        sheets.append_pillar_row(row)
    except Exception as exc:
        row.status = ProcessingStatus.PARTIAL_COMPLETE.value
        row.append_error(f"Google Sheets pillar tab update failed: {public_error_message(exc)}")
        update_sheet()


def send_final_message(telegram: TelegramService, chat_id: int, row: SheetRow, sheet_url: str | None) -> None:
    try:
        if row.status == ProcessingStatus.COMPLETE.value or row.hook:
            telegram.send_message(chat_id, telegram.build_completion_message(row, sheet_url))
        else:
            telegram.send_message(chat_id, telegram.build_failure_message(row, sheet_url))
    except Exception as exc:
        logger.warning("telegram_final_reply_failed", extra={"error": public_error_message(exc)})
