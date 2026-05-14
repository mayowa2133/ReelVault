from app.config import Settings
from app.services.telegram_service import TelegramService, telegram_download_name
from app.models.schemas import TelegramMediaReference


def test_parse_video_upload_from_telegram_update():
    service = TelegramService(Settings())
    update = {
        "message": {
            "message_id": 10,
            "from": {"id": 123},
            "chat": {"id": 456},
            "caption": "tech https://www.instagram.com/reel/ABC123/",
            "video": {
                "file_id": "file-123",
                "file_unique_id": "unique-123",
                "file_size": 1024,
                "mime_type": "video/mp4",
            },
        }
    }

    incoming = service.parse_media_upload(update)

    assert incoming is not None
    assert incoming.chat_id == 456
    assert incoming.user_id == 123
    assert incoming.caption.startswith("tech")
    assert incoming.media.file_id == "file-123"
    assert incoming.media.file_unique_id == "unique-123"


def test_parse_video_document_upload_from_telegram_update():
    service = TelegramService(Settings())
    update = {
        "message": {
            "from": {"id": 123},
            "chat": {"id": 456},
            "document": {
                "file_id": "file-123",
                "file_unique_id": "unique-123",
                "file_name": "manual-upload.mp4",
                "mime_type": "video/mp4",
            },
        }
    }

    incoming = service.parse_media_upload(update)

    assert incoming is not None
    assert incoming.media.file_name == "manual-upload.mp4"
    assert incoming.media.media_type == "document_video"


def test_telegram_download_name_sanitizes_file_name():
    media = TelegramMediaReference(file_id="file-123", file_name="../bad:name.mp4")

    assert telegram_download_name(media, "videos/file_1.mp4") == "bad_name.mp4"
