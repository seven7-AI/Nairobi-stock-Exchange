"""Transactional email tasks.

Task arguments are serialized into the broker and shown in Flower, so these
tasks take a **user id**, never a token or a rendered body containing one. The
token is minted inside the task and goes straight into the message.

    codegraph explore "send_verification_email EmailService create_purpose_token"
"""

from __future__ import annotations

import uuid
from typing import Any

from app.celery_app import celery_app
from app.web.config import get_settings
from app.web.core.security.tokens import TokenType, create_purpose_token
from app.web.db.base import get_sync_session_factory
from app.web.db.models.user import User
from app.web.services.email import EmailMessagePayload, EmailService
from app.web.utils.logger import get_logger

logger = get_logger("app.celery_app.tasks.email_tasks")


def _send_purpose_email(
    user_id: str, token_type: TokenType, subject: str, intro: str
) -> dict[str, Any]:
    settings = get_settings()
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        user = session.get(User, uuid.UUID(user_id))
        if user is None:
            logger.warning("email_user_missing", user_id=user_id)
            return {"status": "skipped", "reason": "user not found"}
        email, role, organization_id = user.email, user.role, user.organization_id

    token = create_purpose_token(
        settings,
        user_id=uuid.UUID(user_id),
        email=email,
        role=role,
        organization_id=organization_id,
        token_type=token_type,
    )
    sent = EmailService(settings).send(
        EmailMessagePayload(to=email, subject=subject, body=f"{intro}\n\n{token}\n")
    )
    return {"status": "sent" if sent else "skipped", "user_id": user_id}


@celery_app.task(name="app.celery_app.tasks.email_tasks.send_verification_email")
def send_verification_email(user_id: str) -> dict[str, Any]:
    """Email a fresh verification token to a user."""
    return _send_purpose_email(
        user_id,
        TokenType.EMAIL_VERIFY,
        "Verify your NSE Analytics account",
        "Confirm your address with this token:",
    )


@celery_app.task(name="app.celery_app.tasks.email_tasks.send_password_reset_email")
def send_password_reset_email(user_id: str) -> dict[str, Any]:
    """Email a password reset token to a user."""
    return _send_purpose_email(
        user_id,
        TokenType.PASSWORD_RESET,
        "Reset your NSE Analytics password",
        "Use this token to set a new password:",
    )


@celery_app.task(name="app.celery_app.tasks.email_tasks.send_report_ready_email")
def send_report_ready_email(recipient: str, kind: str, report_name: str) -> dict[str, Any]:
    """Notify a subscriber that a report has been generated."""
    settings = get_settings()
    sent = EmailService(settings).send(
        EmailMessagePayload(
            to=recipient,
            subject=f"NSE {kind} report ready: {report_name}",
            body=f"The {kind} report {report_name} has been generated.",
        )
    )
    logger.info("report_ready_email", kind=kind, report=report_name, sent=sent)
    return {"status": "sent" if sent else "skipped", "report": report_name}


__all__ = [
    "send_password_reset_email",
    "send_report_ready_email",
    "send_verification_email",
]
