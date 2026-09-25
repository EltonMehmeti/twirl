import json

import httpx

from twirl.config import Settings
from twirl.notify.senders import LogSender, TelegramSender, build_senders


def test_telegram_sender_posts_to_admin_chat():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    sender = TelegramSender(
        token="T", admin_chat_id="999", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert sender.send("admin", "", "hello") == "42"
    assert seen["url"] == "https://api.telegram.org/botT/sendMessage"
    assert seen["json"] == {"chat_id": "999", "text": "hello"}


def test_unconfigured_channels_fall_back_to_logging():
    senders = build_senders(Settings(smtp_host="", telegram_bot_token=""))
    assert isinstance(senders["email"], LogSender)
    assert isinstance(senders["telegram"], LogSender)
