import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from api.apps.notification.schemas import NotificationSchema
from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.core.config import settings
from api.utils.email import get_email_context

logger = logging.getLogger(__name__)


# Search core templates, then all apps templates
def _get_template_loaders() -> list[FileSystemLoader]:
    """
    Get template loaders for Jinja2 environment.
    """
    loaders = [FileSystemLoader("api/templates")]
    apps_dir = Path("api/apps")
    if apps_dir.exists():
        for item in apps_dir.iterdir():
            if item.is_dir():
                app_template_dir = item / "templates"
                if app_template_dir.exists():
                    loaders.append(FileSystemLoader(str(app_template_dir)))
    return loaders


# Setup Jinja2 environment with dynamic app loaders
template_env = Environment(loader=ChoiceLoader(_get_template_loaders()), autoescape=True)


class EmailChannel(BaseNotificationChannel):
    """
    Notification channel that triggers an email-sending Celery task.
    """

    def _render_template(self, notification: NotificationSchema) -> str:
        """Render the Jinja2 HTML template with notification data and global styling ctx."""
        template = template_env.get_template(notification.template_path)

        # Inject standard data
        context = {
            "subject": notification.subject,
            "message": notification.message,
            "action_url": notification.action_url,
            "project_name": settings.PROJECT_NAME,
            "current_year": datetime.now().year,
        }

        # Merge unified styles overriding custom styles provided in metadata
        unified_styles = get_email_context()
        context.update(unified_styles)

        # If the user defines specific properties, they append the context
        if notification.metadata:
            context.update(notification.metadata)

        return str(template.render(**context))

    async def send(self, user_id: UUID, notification: NotificationSchema) -> None:
        """
        Send an email to a specific user by triggering a background Celery task.

        Args:
            user_id (UUID): User ID.
            notification (NotificationSchema): Notification to send.
        """
        from api.apps.notification.tasks import (  # pylint: disable=cyclic-import, import-outside-toplevel
            send_email_worker_task,
        )

        # Expect the target email addresses and attachments in notification metadata
        to_email = notification.metadata.get("email")
        cc_emails = notification.metadata.get("cc", [])
        bcc_emails = notification.metadata.get("bcc", [])
        attachments = notification.metadata.get("attachments", [])

        if not to_email:
            logger.debug("EmailChannel skipped: No 'email' target found in notification metadata for user %s.", user_id)
            return

        html_body = self._render_template(notification)
        subject_text = notification.subject or "New Notification"

        # Dispatch execution to Celery.
        send_email_worker_task.delay(
            to_email=to_email,
            subject=subject_text,
            html_content=html_body,
            cc_emails=cc_emails,
            bcc_emails=bcc_emails,
            attachments=attachments,
        )

    async def broadcast(self, notification: NotificationSchema) -> None:
        """
        We do not support dynamic email broadcasting by default to prevent spamming
        all users. Broadcasting should ideally be done using a worker grouping task.
        """
        logger.warning("EmailChannel broadcast not implemented to prevent accidental mass-mailing.")


email_channel = EmailChannel()
