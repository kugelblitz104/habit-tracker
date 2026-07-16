"""Outbound email.

Provider-agnostic SMTP built on aiosmtplib. Any SMTP provider works via the
``SMTP_*`` settings (Resend: smtp.resend.com / user ``resend`` / password = API
key; SendGrid; Mailgun; …). When ``smtp_host`` is unset — the local-dev default
— messages are logged instead of sent so the calling flow is fully testable
offline; drop real SMTP credentials into the environment to send for real.
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from habit_tracker.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email, or log it when SMTP isn't configured."""
    if not settings.smtp_host:
        logger.warning(
            "SMTP not configured; email to %s NOT sent.\nSubject: %s\n%s",
            to,
            subject,
            body,
        )
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    # Port 465 speaks TLS from the first byte (implicit); 587/2587 upgrade an
    # initially-plaintext connection via STARTTLS. Passing both would error.
    tls_kwargs = (
        {"use_tls": True} if settings.smtp_port == 465 else {"start_tls": True}
    )

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        **tls_kwargs,
    )
    logger.info("Sent email to %s (subject: %s)", to, subject)


async def send_password_reset_email(to: str, reset_link: str) -> None:
    subject = "Reset your Habit Tracker password"
    body = (
        "We received a request to reset your Habit Tracker password.\n\n"
        f"Reset it using the link below (it expires in "
        f"{settings.reset_token_expiry_minutes} minutes):\n\n"
        f"{reset_link}\n\n"
        "If you didn't request this, you can safely ignore this email — your "
        "password won't change."
    )
    await send_email(to, subject, body)
