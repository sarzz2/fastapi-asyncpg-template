"""
Low-level Celery background worker tasks for notification channels (FCM push, SendGrid email).
"""

import logging
import os
from typing import Any

import certifi
from firebase_admin import messaging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    Bcc,
    Cc,
    Content,
    Disposition,
    Email,
    FileContent,
    FileName,
    FileType,
    Mail,
    To,
)

from api.apps.notification.v0.dao.device import DeviceDAO
from api.core.celery_app import AsyncBaseTask, celery_app
from api.core.config import settings
from api.utils.firebase import get_firebase_app

# Fix for macOS local development SSL certificate errors:
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["SSL_CERT_DIR"] = certifi.where()

logger = logging.getLogger(__name__)


def _deactivate_tokens(task: AsyncBaseTask, tokens: list[str]) -> None:
    """Helper to deactivate dead tokens using worker event loop."""

    async def _prune() -> None:
        dao = DeviceDAO(task.container.db)
        await dao.deactivate_tokens(tokens)

    task.loop.run_until_complete(_prune())


@celery_app.task(name="send_email_worker_task", bind=True)
def send_email_worker_task(
    _self: AsyncBaseTask,
    to_email: str | list[str],
    subject: str,
    html_content: str,
    cc_emails: list[str] | None = None,
    bcc_emails: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """
    Celery task to send an email using SendGrid in the background.
    Supports multiple recipients, cc, bcc, and attachments.
    """
    if not settings.SENDGRID_API_KEY or not settings.EMAILS_FROM_EMAIL:
        logger.warning("SendGrid API Key or From Email not configured. Skipping email.")
        return

    logger.info("Executing task: send_email_worker_task to %s", to_email)

    if isinstance(to_email, str):
        to_list = [To(to_email)]
    else:
        to_list = [To(email) for email in to_email]

    message = Mail(
        from_email=Email(settings.EMAILS_FROM_EMAIL, settings.EMAILS_FROM_NAME or "FastAPI Template"),
        to_emails=to_list,
        subject=subject,
        html_content=Content("text/html", html_content),
    )

    if cc_emails:
        message.cc = [Cc(email) for email in cc_emails]

    if bcc_emails:
        message.bcc = [Bcc(email) for email in bcc_emails]

    if attachments:
        sg_attachments: list[Attachment] = []
        for att in attachments:
            try:
                attachment = Attachment()
                attachment.file_content = FileContent(att.get("content"))
                attachment.file_type = FileType(att.get("type", "application/octet-stream"))
                attachment.file_name = FileName(att.get("filename", "attachment"))
                attachment.disposition = Disposition(att.get("disposition", "attachment"))
                sg_attachments.append(attachment)
            except (KeyError, ValueError, TypeError, AttributeError):
                logger.exception("Failed to parse attachment %s", att.get("filename"))
        if sg_attachments:
            message.attachment = sg_attachments

    try:
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info("SendGrid email sent. Status code: %s", response.status_code)
    except (OSError, RuntimeError, ValueError):
        logger.exception("Failed to send email to %s", to_email)
        raise


@celery_app.task(name="send_fcm_push_worker_task", bind=True)
def send_fcm_push_worker_task(
    self: AsyncBaseTask,
    tokens: list[str],
    title: str | None,
    body: str,
    data: dict[str, Any] | None = None,
) -> None:
    """
    Celery task to send push notifications via Firebase Cloud Messaging (FCM).
    Prunes dead / unregistered tokens automatically.
    """
    if not tokens:
        return

    app = get_firebase_app()
    if not app:
        logger.warning("FCM app not initialized. Cannot dispatch push notification to %d tokens.", len(tokens))
        return

    logger.info("Executing task: send_fcm_push_worker_task to %d devices", len(tokens))

    notification = messaging.Notification(title=title or "New Notification", body=body)
    str_data = {str(k): str(v) for k, v in (data or {}).items()}

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=notification,
        data=str_data,
    )

    response = messaging.send_each_for_multicast(message, app=app)
    logger.info(
        "FCM multicast sent: %d successes, %d failures",
        response.success_count,
        response.failure_count,
    )

    dead_tokens: list[str] = []
    for idx, send_response in enumerate(response.responses):
        if not send_response.success and send_response.exception:
            code = getattr(send_response.exception, "code", "")
            if code in ("NOT_FOUND", "UNREGISTERED", "INVALID_ARGUMENT"):
                dead_tokens.append(tokens[idx])

    if dead_tokens:
        logger.info("Pruning %d dead FCM tokens", len(dead_tokens))
        _deactivate_tokens(self, dead_tokens)
