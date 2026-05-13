from app.config import Settings
from app.services.telegram_service import TelegramService


def test_parse_callback_query():
    service = TelegramService(Settings())
    callback = service.parse_callback_query(
        {
            "callback_query": {
                "id": "callback-id",
                "from": {"id": 123},
                "message": {"message_id": 10, "chat": {"id": 456}},
                "data": "rvp:ai:7:",
            }
        }
    )

    assert callback is not None
    assert callback.callback_query_id == "callback-id"
    assert callback.user_id == 123
    assert callback.chat_id == 456
    assert callback.message_id == 10
    assert callback.data == "rvp:ai:7:"
