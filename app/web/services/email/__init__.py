"""Transactional email: verification, invitations, resets, report delivery."""

from app.web.services.email.sender import EmailMessagePayload, EmailService

__all__ = ["EmailMessagePayload", "EmailService"]
