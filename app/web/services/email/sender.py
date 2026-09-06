"""Transactional email.

Bodies may reference a user by name and address; they must never embed a raw
token in a log line. The send helpers log the template and recipient domain
only — see ``app/web/utils/logger.py``.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.web.config import Settings
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.email")


@dataclass(frozen=True)
class EmailMessagePayload:
    """RORO payload for a single outbound message."""

    to: str
    subject: str
    body: str
    html_body: str | None = None


class EmailService:
    """SMTP sender. Falls back to logging when SMTP is unconfigured (local dev)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.smtp_host)

    def send(self, payload: EmailMessagePayload) -> bool:
        """Send one message. Returns whether it was actually dispatched."""
        recipient_domain = payload.to.rpartition("@")[2]
        if not self.is_configured:
            logger.info(
                "email_skipped_smtp_unconfigured",
                subject=payload.subject,
                recipient_domain=recipient_domain,
            )
            return False

        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = payload.to
        message["Subject"] = payload.subject
        message.set_content(payload.body)
        if payload.html_body:
            message.add_alternative(payload.html_body, subtype="html")

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port) as server:
            server.starttls()
            if self._settings.smtp_user:
                server.login(self._settings.smtp_user, self._settings.smtp_password)
            server.send_message(message)

        logger.info("email_sent", subject=payload.subject, recipient_domain=recipient_domain)
        return True


__all__ = ["EmailMessagePayload", "EmailService"]
