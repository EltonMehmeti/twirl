import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from twirl.config import Settings
from twirl.notify.templates import ADMIN_RECIPIENT

log = logging.getLogger(__name__)


class Sender(Protocol):
    def send(self, recipient: str, subject: str, body: str) -> str | None: ...


class LogSender:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    def send(self, recipient: str, subject: str, body: str) -> str | None:
        log.info("[%s -> %s] %s\n%s", self.channel, recipient, subject, body)
        return None


class EmailSender:
    def __init__(self, *, host: str, port: int, user: str, password: str, sender: str) -> None:
        self.host, self.port, self.user, self.password, self.sender = (
            host,
            port,
            user,
            password,
            sender,
        )

    def send(self, recipient: str, subject: str, body: str) -> str | None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)
        return None


class TelegramSender:
    def __init__(
        self, *, token: str, admin_chat_id: str, client: httpx.Client | None = None
    ) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.admin_chat_id = admin_chat_id
        self.client = client or httpx.Client(timeout=10)

    def send(self, recipient: str, subject: str, body: str) -> str | None:
        chat_id = self.admin_chat_id if recipient == ADMIN_RECIPIENT else recipient
        text = f"{subject}\n\n{body}" if subject else body
        response = self.client.post(self.url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
        return str(response.json()["result"]["message_id"])


def build_senders(settings: Settings) -> dict[str, Sender]:
    email: Sender = (
        EmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password,
            sender=settings.mail_from,
        )
        if settings.smtp_host
        else LogSender("email")
    )
    telegram: Sender = (
        TelegramSender(
            token=settings.telegram_bot_token, admin_chat_id=settings.telegram_admin_chat_id
        )
        if settings.telegram_bot_token and settings.telegram_admin_chat_id
        else LogSender("telegram")
    )
    return {"email": email, "telegram": telegram}
