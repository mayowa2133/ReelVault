from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.models.schemas import ContentPillar, SheetRow
from app.services.pillar_service import PillarService
from app.utils.errors import TelegramSendError, public_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IncomingTelegramMessage:
    chat_id: int
    user_id: int
    text: str
    message_id: int | None = None


@dataclass(frozen=True)
class IncomingTelegramCallback:
    callback_query_id: str
    chat_id: int
    user_id: int
    data: str
    message_id: int | None = None


class TelegramService:
    """Small direct Telegram Bot API wrapper."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def parse_update(self, payload: dict[str, Any]) -> IncomingTelegramMessage | None:
        message = payload.get("message") or payload.get("edited_message")
        if not isinstance(message, dict):
            return None

        text = message.get("text") or message.get("caption")
        user = message.get("from") or {}
        chat = message.get("chat") or {}
        if not text or "id" not in user or "id" not in chat:
            return None

        return IncomingTelegramMessage(
            chat_id=int(chat["id"]),
            user_id=int(user["id"]),
            text=str(text),
            message_id=message.get("message_id"),
        )

    def parse_callback_query(self, payload: dict[str, Any]) -> IncomingTelegramCallback | None:
        callback = payload.get("callback_query")
        if not isinstance(callback, dict):
            return None

        data = callback.get("data")
        user = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        if not data or "id" not in callback or "id" not in user or "id" not in chat:
            return None

        return IncomingTelegramCallback(
            callback_query_id=str(callback["id"]),
            chat_id=int(chat["id"]),
            user_id=int(user["id"]),
            data=str(data),
            message_id=message.get("message_id"),
        )

    def is_allowed_user(self, user_id: int) -> bool:
        allowed_user_id = self.settings.telegram_allowed_user_id
        return allowed_user_id is None or allowed_user_id == user_id

    async def send_message_async(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        token = self._token()
        payload = self._message_payload(chat_id, text, reply_markup)
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
            self._validate_response(response)
        except Exception as exc:
            raise TelegramSendError(f"Telegram send failed: {public_error_message(exc)}", step="telegram") from exc

    def send_message(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        token = self._token()
        payload = self._message_payload(chat_id, text, reply_markup)
        try:
            with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                response = client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
            self._validate_response(response)
        except Exception as exc:
            raise TelegramSendError(f"Telegram send failed: {public_error_message(exc)}", step="telegram") from exc

    async def answer_callback_query_async(self, callback_query_id: str, text: str = "") -> None:
        token = self._token()
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json=payload)
            self._validate_response(response)
        except Exception as exc:
            raise TelegramSendError(f"Telegram callback answer failed: {public_error_message(exc)}", step="telegram") from exc

    async def edit_message_text_async(self, chat_id: int, message_id: int, text: str) -> None:
        token = self._token()
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": self._truncate_message(text),
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.post(f"https://api.telegram.org/bot{token}/editMessageText", json=payload)
            self._validate_response(response)
        except Exception as exc:
            raise TelegramSendError(f"Telegram message edit failed: {public_error_message(exc)}", step="telegram") from exc

    async def send_pillar_confirmation_async(
        self,
        chat_id: int,
        row_index: int,
        pillar: ContentPillar,
        reel_url: str,
    ) -> None:
        await self.send_message_async(
            chat_id,
            f"Did you mean {pillar.value} for this Reel?\n{reel_url}",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": f"Yes, use {pillar.value}",
                            "callback_data": PillarService.build_callback_data("confirm", row_index, pillar),
                        }
                    ],
                    [
                        {
                            "text": "Let AI classify",
                            "callback_data": PillarService.build_callback_data("ai", row_index),
                        },
                        {
                            "text": "Cancel",
                            "callback_data": PillarService.build_callback_data("cancel", row_index),
                        },
                    ],
                ]
            },
        )

    def build_completion_message(self, row: SheetRow, sheet_url: str | None) -> str:
        lines = [f"Reel inspiration saved. Status: {row.status}"]
        if row.pillar:
            lines.append(f"\nPillar: {row.pillar}")
        if row.hook:
            lines.append(f"\nHook: {row.hook}")
        if row.summary:
            lines.append(f"\nSummary: {row.summary}")

        ideas = [row.original_idea_1, row.original_idea_2, row.original_idea_3]
        compact_ideas = [idea.splitlines()[0] for idea in ideas if idea]
        if compact_ideas:
            lines.append("\nOriginal content ideas:")
            for index, idea in enumerate(compact_ideas, start=1):
                lines.append(f"{index}. {idea}")

        if sheet_url:
            lines.append(f"\nGoogle Sheet: {sheet_url}")
        if row.script_title:
            lines.append(f"Script: {row.script_title}")
        if row.inspiration_folder_link:
            lines.append(f"Inspiration folder: {row.inspiration_folder_link}")
        if row.script_google_doc_link:
            lines.append(f"Google Doc script: {row.script_google_doc_link}")
        if row.custom_script:
            preview_lines = row.custom_script.splitlines()[:3]
            lines.append("\nScript preview:")
            lines.extend(preview_lines)
        if row.drive_video_link:
            lines.append(f"Google Drive video: {row.drive_video_link}")
        if row.drive_audio_link:
            lines.append(f"Google Drive audio: {row.drive_audio_link}")
        if row.error_message:
            first_error = row.error_message.splitlines()[0]
            lines.append(f"\nNote: {first_error}")
        return self._truncate_message("\n".join(lines))

    def build_failure_message(self, row: SheetRow, sheet_url: str | None) -> str:
        lines = [
            "I saved what I could, but this Reel needs manual review.",
            f"Status: {row.status}",
        ]
        if sheet_url:
            lines.append(f"Google Sheet: {sheet_url}")
        if row.error_message:
            lines.append(f"Reason: {row.error_message.splitlines()[0]}")
        return self._truncate_message("\n".join(lines))

    def _token(self) -> str:
        if not self.settings.telegram_bot_token:
            raise TelegramSendError("TELEGRAM_BOT_TOKEN is not configured", step="telegram")
        return self.settings.telegram_bot_token

    def _message_payload(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": self._truncate_message(text),
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return payload

    def _validate_response(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise TelegramSendError(f"Telegram API returned HTTP {response.status_code}", step="telegram")
        data = response.json()
        if not data.get("ok"):
            description = data.get("description", "unknown Telegram API error")
            raise TelegramSendError(f"Telegram API error: {description}", step="telegram")

    def _truncate_message(self, text: str) -> str:
        if len(text) <= 3900:
            return text
        return text[:3860] + "\n[truncated]"
