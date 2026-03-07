import logging
import os
from typing import Optional
from uuid import UUID

import certifi
from celery import Task
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

from api.apps.notification.schemas import NotificationType
from api.apps.notification.v0.service import notification_service
from api.core.celery_app import celery_app
from api.core.config import settings

# Fix for macOS local development SSL certificate errors:
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["SSL_CERT_DIR"] = certifi.where()

log = logging.getLogger(__name__)


@celery_app.task(name="send_notification_task", bind=True)
def send_notification_task(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    self: Task,
    user_id_str: str,
    message: str,
    notification_type: str = NotificationType.INFO.value,
    subject: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Celery task to send a notification background.
    """
    user_id = UUID(user_id_str)
    type_enum = NotificationType(notification_type)

    async def _send() -> None:
        await notification_service.notify(
            user_id=user_id,
            message=message,
            notification_type=type_enum,
            subject=subject,
            metadata=metadata,
        )

    try:
        # Use the worker's event loop to run the async method
        self.loop.run_until_complete(_send())
    except Exception as e:  # pylint: disable=broad-except
        log.error("Error sending background notification to user %s: %s", user_id, e)


@celery_app.task(name="broadcast_notification_task", bind=True)
def broadcast_notification_task(
    self: Task,
    message: str,
    notification_type: str = NotificationType.INFO.value,
    subject: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Celery task to broadcast a notification in background.
    """
    type_enum = NotificationType(notification_type)

    async def _broadcast() -> None:
        await notification_service.broadcast_all(
            message=message,
            notification_type=type_enum,
            subject=subject,
            metadata=metadata,
        )

    try:
        self.loop.run_until_complete(_broadcast())
    except Exception as e:  # pylint: disable=broad-except
        log.error("Error broadcasting background notification: %s", e)


@celery_app.task(name="send_email_worker_task", bind=True)
def send_email_worker_task(  # pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
    self: Task,
    to_email: str | list[str],
    subject: str,
    html_content: str,
    cc_emails: Optional[list[str]] = None,
    bcc_emails: Optional[list[str]] = None,
    attachments: Optional[list[dict]] = None,
) -> None:
    """
    Celery task to send an email using SendGrid in the background.
    Supports multiple recipients, cc, bcc, and attachments.
    """
    if not settings.SENDGRID_API_KEY or not settings.EMAILS_FROM_EMAIL:
        log.warning("SendGrid API Key or From Email not configured. Skipping email.")
        return

    # Build primary To list
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

    # Add CCs if present
    if cc_emails:
        message.cc = [Cc(email) for email in cc_emails]

    # Add BCCs if present
    if bcc_emails:
        message.bcc = [Bcc(email) for email in bcc_emails]

    # Add Attachments if present
    if attachments:
        sg_attachments = []
        for att in attachments:
            try:
                attachment = Attachment()
                attachment.file_content = FileContent(att.get("content"))
                attachment.file_type = FileType(att.get("type", "application/octet-stream"))
                attachment.file_name = FileName(att.get("filename", "attachment"))
                attachment.disposition = Disposition(att.get("disposition", "attachment"))
                sg_attachments.append(attachment)
            except Exception as e:  # pylint: disable=broad-except
                log.error("Failed to parse attachment %s: %s", att.get("filename"), e)
        if sg_attachments:
            message.attachment = sg_attachments

    try:
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        log.info("SendGrid email sent. Status code: %s", response.status_code)
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.error("Failed to send email to %s: %s", to_email, str(e))
        raise e
