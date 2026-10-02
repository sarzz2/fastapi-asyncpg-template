import logging
import os

import firebase_admin
from firebase_admin import credentials

from api.core.config import settings

logger = logging.getLogger("fastapi")


def get_firebase_app() -> firebase_admin.App | None:
    """
    Retrieve or initialize the Firebase Admin app instance.
    Returns None if credentials path is not configured or file is not found.
    """
    try:
        return firebase_admin.get_app()
    except ValueError:
        if not settings.FIREBASE_CREDENTIALS_PATH or not os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
            logger.warning("Firebase credentials not configured or file not found. Skipping FCM.")
            return None
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        return firebase_admin.initialize_app(cred)
