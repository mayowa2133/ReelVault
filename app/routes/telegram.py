from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.models.schemas import (
    ContentPillar,
    ProcessingStatus,
    ProcessingTaskPayload,
    ReelReference,
    SheetRow,
    TelegramMediaReference,
)
from app.services.google_sheets_service import GoogleSheetsService
from app.services.pillar_service import PillarParseKind, PillarService
from app.services.social_video_service import SocialVideoService
from app.services.task_queue_service import CloudTasksQueueService, is_uncertain_cloud_tasks_timeout
from app.services.telegram_service import IncomingTelegramMedia, TelegramService
from app.services.workflow_service import process_reel_inspiration
from app.utils.errors import public_error_message
from app.utils.logging import get_logger

router = APIRouter(tags=["telegram"])
logger = get_logger(__name__)


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> dict[str, int | bool | str]:
    if settings.telegram_webhook_secret:
        supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if supplied_secret != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    payload = await request.json()
    telegram = TelegramService(settings)

    callback = telegram.parse_callback_query(payload)
    if callback is not None:
        return await handle_pillar_callback(callback, telegram, background_tasks, settings)

    media_upload = telegram.parse_media_upload(payload)
    if media_upload is not None:
        return await handle_media_upload(media_upload, telegram, background_tasks, settings)

    incoming = telegram.parse_update(payload)

    if incoming is None:
        return {"ok": True, "queued": 0, "message": "No text message found"}

    if not telegram.is_allowed_user(incoming.user_id):
        logger.warning("telegram_unauthorized_user", extra={"telegram_user_id": incoming.user_id})
        return {"ok": True, "queued": 0, "message": "Ignored unauthorized user"}

    reels = SocialVideoService.extract_supported_urls(incoming.text)
    if not reels:
        try:
            await telegram.send_message_async(
                incoming.chat_id,
                "Please send one or more YouTube, Instagram, TikTok, or X video URLs.",
            )
        except Exception as exc:
            logger.warning("telegram_invalid_url_reply_failed", extra={"error": public_error_message(exc)})
        return {"ok": True, "queued": 0, "message": "No supported video URLs found"}

    pillar_result = PillarService.parse_message(incoming.text)
    if pillar_result.kind == PillarParseKind.AMBIGUOUS:
        candidates = ", ".join(pillar.value for pillar in pillar_result.candidates)
        try:
            await telegram.send_message_async(
                incoming.chat_id,
                f"I found multiple possible pillars ({candidates}). Please send one Reel with one pillar.",
            )
        except Exception as exc:
            logger.warning("telegram_ambiguous_pillar_reply_failed", extra={"error": public_error_message(exc)})
        return {"ok": True, "queued": 0, "message": "Ambiguous pillar"}

    if pillar_result.should_confirm and pillar_result.pillar:
        pending_count = await create_pending_pillar_confirmations(
            reels=reels,
            chat_id=incoming.chat_id,
            pillar_result=pillar_result,
            telegram=telegram,
            settings=settings,
        )
        return {"ok": True, "queued": 0, "pending": pending_count}

    start_message = (
        "Got it - saving this video inspiration now."
        if len(reels) == 1
        else f"Got it - saving {len(reels)} video inspirations now."
    )
    try:
        await telegram.send_message_async(incoming.chat_id, start_message)
    except Exception as exc:
        logger.warning("telegram_start_reply_failed", extra={"error": public_error_message(exc)})

    initial_pillar = pillar_result.pillar if pillar_result.kind in {PillarParseKind.EXACT, PillarParseKind.ALIAS} else None
    initial_pillar_source = pillar_result.source if initial_pillar else ""
    queued_count = 0
    for reel in reels:
        if await schedule_reel_processing(
            reel=reel,
            chat_id=incoming.chat_id,
            settings=settings,
            background_tasks=background_tasks,
            telegram=telegram,
            initial_pillar=initial_pillar,
            initial_pillar_source=initial_pillar_source,
        ):
            queued_count += 1

    return {"ok": True, "queued": queued_count}


async def handle_media_upload(
    incoming: IncomingTelegramMedia,
    telegram: TelegramService,
    background_tasks: BackgroundTasks,
    settings: Settings,
) -> dict[str, int | bool | str]:
    if not telegram.is_allowed_user(incoming.user_id):
        logger.warning("telegram_unauthorized_media_user", extra={"telegram_user_id": incoming.user_id})
        return {"ok": True, "queued": 0, "message": "Ignored unauthorized user"}

    if not settings.enable_telegram_media_fallback:
        await telegram.send_message_async(
            incoming.chat_id,
            "Telegram media fallback is disabled. Send a supported video URL instead.",
        )
        return {"ok": True, "queued": 0, "message": "Telegram media fallback disabled"}

    if incoming.media.file_size and incoming.media.file_size > settings.telegram_media_max_size_mb * 1024 * 1024:
        await telegram.send_message_async(
            incoming.chat_id,
            f"That file is larger than TELEGRAM_MEDIA_MAX_SIZE_MB ({settings.telegram_media_max_size_mb} MB).",
        )
        return {"ok": True, "queued": 0, "message": "Telegram media too large"}

    reels = SocialVideoService.extract_supported_urls(incoming.caption)
    if len(reels) > 1:
        await telegram.send_message_async(
            incoming.chat_id,
            "Please send one uploaded video with at most one supported video URL in the caption.",
        )
        return {"ok": True, "queued": 0, "message": "Multiple caption video URLs"}

    reel = reels[0] if reels else reel_reference_for_media_upload(incoming.media)
    pillar_result = PillarService.parse_message(incoming.caption)
    if pillar_result.kind == PillarParseKind.AMBIGUOUS:
        candidates = ", ".join(pillar.value for pillar in pillar_result.candidates)
        await telegram.send_message_async(
            incoming.chat_id,
            f"I found multiple possible pillars ({candidates}). Please resend this video with one pillar.",
        )
        return {"ok": True, "queued": 0, "message": "Ambiguous pillar"}

    if pillar_result.should_confirm and pillar_result.pillar:
        row = SheetRow.from_telegram_media(reel, incoming.media)
        row.status = ProcessingStatus.PENDING_PILLAR_CONFIRMATION.value
        row.pillar = pillar_result.pillar.value
        row.pillar_source = pillar_result.source
        row.pillar_confidence = f"{pillar_result.confidence or 0:.2f}"
        try:
            row_index = GoogleSheetsService(settings).append_row(row)
            await telegram.send_pillar_confirmation_async(incoming.chat_id, row_index, pillar_result.pillar, reel.url)
            return {"ok": True, "queued": 0, "pending": 1}
        except Exception as exc:
            logger.warning("pending_media_pillar_confirmation_failed", extra={"error": public_error_message(exc)})
            await telegram.send_message_async(
                incoming.chat_id,
                f"I could not create a pending confirmation for this upload: {public_error_message(exc)}",
            )
            return {"ok": True, "queued": 0, "message": "Pending media confirmation failed"}

    try:
        await telegram.send_message_async(incoming.chat_id, "Got it - saving this uploaded video now.")
    except Exception as exc:
        logger.warning("telegram_media_start_reply_failed", extra={"error": public_error_message(exc)})

    initial_pillar = pillar_result.pillar if pillar_result.kind in {PillarParseKind.EXACT, PillarParseKind.ALIAS} else None
    initial_pillar_source = pillar_result.source if initial_pillar else "ai"
    queued = await schedule_reel_processing(
        reel=reel,
        chat_id=incoming.chat_id,
        settings=settings,
        background_tasks=background_tasks,
        telegram=telegram,
        initial_pillar=initial_pillar,
        initial_pillar_source=initial_pillar_source,
        telegram_media=incoming.media,
    )
    return {"ok": True, "queued": 1 if queued else 0}


async def create_pending_pillar_confirmations(
    *,
    reels,
    chat_id: int,
    pillar_result,
    telegram: TelegramService,
    settings: Settings,
) -> int:
    sheets = GoogleSheetsService(settings)
    pending_count = 0
    for reel in reels:
        row = SheetRow.from_reel(reel)
        row.status = ProcessingStatus.PENDING_PILLAR_CONFIRMATION.value
        row.pillar = pillar_result.pillar.value
        row.pillar_source = pillar_result.source
        row.pillar_confidence = f"{pillar_result.confidence or 0:.2f}"
        try:
            row_index = sheets.append_row(row)
            await telegram.send_pillar_confirmation_async(chat_id, row_index, pillar_result.pillar, reel.url)
            pending_count += 1
        except Exception as exc:
            logger.warning(
                "pending_pillar_confirmation_failed",
                extra={"shortcode": reel.shortcode, "error": public_error_message(exc)},
            )
            try:
                await telegram.send_message_async(
                    chat_id,
                    f"I could not create a pending confirmation for {reel.url}: {public_error_message(exc)}",
                )
            except Exception as send_exc:
                logger.warning("telegram_pending_pillar_failure_reply_failed", extra={"error": public_error_message(send_exc)})
    return pending_count


async def handle_pillar_callback(
    callback,
    telegram: TelegramService,
    background_tasks: BackgroundTasks,
    settings: Settings,
) -> dict[str, int | bool | str]:
    if not telegram.is_allowed_user(callback.user_id):
        logger.warning("telegram_unauthorized_callback", extra={"telegram_user_id": callback.user_id})
        return {"ok": True, "queued": 0, "message": "Ignored unauthorized user"}

    action = PillarService.parse_callback_data(callback.data)
    if action is None:
        return {"ok": True, "queued": 0, "message": "Ignored callback"}

    try:
        await telegram.answer_callback_query_async(callback.callback_query_id)
    except Exception as exc:
        logger.warning("telegram_callback_answer_failed", extra={"error": public_error_message(exc)})

    sheets = GoogleSheetsService(settings)
    try:
        row = sheets.get_row(action.row_index)
    except Exception as exc:
        await telegram.send_message_async(callback.chat_id, f"I could not find that pending Reel row: {public_error_message(exc)}")
        return {"ok": True, "queued": 0, "message": "Pending row not found"}

    if row.status != ProcessingStatus.PENDING_PILLAR_CONFIRMATION.value:
        await acknowledge_callback_choice(
            telegram,
            callback.chat_id,
            callback.message_id,
            f"This Reel is already marked as {row.status}.",
        )
        return {"ok": True, "queued": 0, "message": "Callback already handled"}

    if action.action == "cancel":
        row.status = ProcessingStatus.CANCELLED.value
        row.append_error("Cancelled from Telegram pillar confirmation.")
        try:
            sheets.update_row(action.row_index, row)
        except Exception as exc:
            logger.warning("cancelled_row_update_failed", extra={"row_index": action.row_index, "error": public_error_message(exc)})
        await acknowledge_callback_choice(telegram, callback.chat_id, callback.message_id, "Cancelled this video inspiration.")
        return {"ok": True, "queued": 0, "message": "Cancelled"}

    media = row.to_telegram_media_reference()
    reel = row.to_reel_reference() if media else SocialVideoService.normalize_url(row.reel_url)
    if reel is None:
        row.status = ProcessingStatus.INVALID_URL.value
        row.append_error("Stored pending row has an invalid supported video URL.")
        try:
            sheets.update_row(action.row_index, row)
        except Exception as exc:
            logger.warning("invalid_pending_url_update_failed", extra={"row_index": action.row_index, "error": public_error_message(exc)})
        await telegram.send_message_async(callback.chat_id, "That pending row does not have a valid supported video URL.")
        return {"ok": True, "queued": 0, "message": "Invalid pending video URL"}

    if action.action == "confirm" and action.pillar is not None:
        row.pillar = action.pillar.value
        row.pillar_source = "telegram_fuzzy_confirmed"
        row.pillar_confidence = "1.00"
        confirmation_text = f"Using {action.pillar.value}. Saving this video inspiration now."
        initial_pillar = action.pillar
        initial_pillar_source = "telegram_fuzzy_confirmed"
    else:
        row.pillar = ""
        row.pillar_source = "ai"
        row.pillar_confidence = ""
        confirmation_text = "Letting AI classify this video. Saving this video inspiration now."
        initial_pillar = None
        initial_pillar_source = "ai"

    row.status = ProcessingStatus.RECEIVED.value
    try:
        sheets.update_row(action.row_index, row)
    except Exception as exc:
        logger.warning("confirmed_pillar_row_update_failed", extra={"row_index": action.row_index, "error": public_error_message(exc)})

    await acknowledge_callback_choice(telegram, callback.chat_id, callback.message_id, confirmation_text)
    queued = await schedule_reel_processing(
        reel=reel,
        chat_id=callback.chat_id,
        settings=settings,
        background_tasks=background_tasks,
        telegram=telegram,
        initial_pillar=initial_pillar,
        initial_pillar_source=initial_pillar_source,
        existing_row_index=action.row_index,
        telegram_media=media,
    )
    return {"ok": True, "queued": 1 if queued else 0}


async def acknowledge_callback_choice(
    telegram: TelegramService,
    chat_id: int,
    message_id: int | None,
    text: str,
) -> None:
    try:
        if message_id is not None:
            await telegram.edit_message_text_async(chat_id, message_id, text)
        else:
            await telegram.send_message_async(chat_id, text)
    except Exception as exc:
        logger.warning("telegram_callback_ack_failed", extra={"error": public_error_message(exc)})


async def schedule_reel_processing(
    *,
    reel: ReelReference,
    chat_id: int,
    settings: Settings,
    background_tasks: BackgroundTasks,
    telegram: TelegramService,
    initial_pillar: ContentPillar | None = None,
    initial_pillar_source: str = "",
    existing_row_index: int | None = None,
    telegram_media: TelegramMediaReference | None = None,
) -> bool:
    if settings.processing_backend == "cloud_tasks":
        return await enqueue_cloud_task(
            reel=reel,
            chat_id=chat_id,
            settings=settings,
            telegram=telegram,
            initial_pillar=initial_pillar,
            initial_pillar_source=initial_pillar_source,
            existing_row_index=existing_row_index,
            telegram_media=telegram_media,
        )

    background_tasks.add_task(
        process_reel_inspiration,
        reel,
        chat_id,
        settings,
        initial_pillar,
        initial_pillar_source,
        existing_row_index,
        telegram_media,
    )
    return True


async def enqueue_cloud_task(
    *,
    reel: ReelReference,
    chat_id: int,
    settings: Settings,
    telegram: TelegramService,
    initial_pillar: ContentPillar | None = None,
    initial_pillar_source: str = "",
    existing_row_index: int | None = None,
    telegram_media: TelegramMediaReference | None = None,
) -> bool:
    sheets = GoogleSheetsService(settings)
    row_index: int | None = existing_row_index
    try:
        if row_index is None:
            row = SheetRow.from_telegram_media(reel, telegram_media) if telegram_media else SheetRow.from_reel(reel)
        else:
            row = sheets.get_row(row_index)
            if telegram_media:
                row.apply_telegram_media(telegram_media)

        apply_queue_metadata(row, initial_pillar, initial_pillar_source)
        if row_index is None:
            row_index = sheets.append_row(row)
        else:
            sheets.update_row(row_index, row)
    except Exception as exc:
        error = public_error_message(exc)
        logger.warning(
            "cloud_task_row_save_failed",
            extra={"shortcode": reel.shortcode, "row_index": row_index, "error": error},
        )
        try:
            await telegram.send_message_async(chat_id, f"I could not save this video before queueing it: {error}")
        except Exception as send_exc:
            logger.warning("telegram_row_save_failure_reply_failed", extra={"error": public_error_message(send_exc)})
        return False

    task_payload = ProcessingTaskPayload(
        reel=reel,
        chat_id=chat_id,
        row_index=row_index,
        initial_pillar=initial_pillar,
        initial_pillar_source=initial_pillar_source,
        telegram_media=telegram_media,
    )
    try:
        CloudTasksQueueService(settings).enqueue_processing_task(task_payload)
        return True
    except Exception as exc:
        error = public_error_message(exc)
        if is_uncertain_cloud_tasks_timeout(exc):
            logger.warning(
                "cloud_task_enqueue_confirmation_timed_out",
                extra={"shortcode": reel.shortcode, "row_index": row_index, "error": error},
            )
            return True

        logger.warning(
            "cloud_task_enqueue_failed",
            extra={"shortcode": reel.shortcode, "row_index": row_index, "error": error},
        )
        try:
            row = sheets.get_row(row_index)
            row.status = ProcessingStatus.QUEUE_FAILED.value
            row.append_error(f"Cloud Tasks enqueue failed: {error}")
            sheets.update_row(row_index, row)
        except Exception as sheet_exc:
            logger.warning("queue_failed_row_update_failed", extra={"error": public_error_message(sheet_exc)})
        try:
            await telegram.send_message_async(chat_id, f"I saved the video URL, but could not queue processing: {error}")
        except Exception as send_exc:
            logger.warning("telegram_queue_failure_reply_failed", extra={"error": public_error_message(send_exc)})
        return False


def apply_queue_metadata(
    row: SheetRow,
    initial_pillar: ContentPillar | None,
    initial_pillar_source: str,
) -> None:
    row.status = ProcessingStatus.QUEUED.value
    if initial_pillar:
        row.pillar = initial_pillar.value
        row.pillar_source = initial_pillar_source
        row.pillar_confidence = "1.00"
    elif initial_pillar_source:
        row.pillar = ""
        row.pillar_source = initial_pillar_source
        row.pillar_confidence = ""


def reel_reference_for_media_upload(media: TelegramMediaReference) -> ReelReference:
    media_id = media.file_unique_id or media.file_id[:24]
    return ReelReference(
        url=f"telegram-upload://{media_id}",
        shortcode=media_id[:32],
        provider="telegram",
    )
