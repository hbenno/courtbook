"""Email sending via SMTP."""

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP."""
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port)


async def send_password_reset_email(to: str, token: str) -> None:
    """Send the password reset email with the reset link."""
    link = f"{settings.frontend_url}/reset-password?token={token}"
    body = (
        f"Hi,\n\n"
        f"You requested a password reset for your CourtBook account.\n\n"
        f"Click the link below to reset your password:\n"
        f"{link}\n\n"
        f"This link expires in {settings.password_reset_expire_minutes} minutes.\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"CourtBook"
    )
    await send_email(to, "Reset your CourtBook password", body)
    logger.info("Password reset email sent to %s", to)
