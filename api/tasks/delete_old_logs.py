import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from celery import Task

from api.core.celery_app import celery_app

log = logging.getLogger(__name__)

# Define the logs directory relative to this file's location
LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


@celery_app.task(bind=True)
def delete_old_logs(_self: Task | None = None) -> None:
    """
    Deletes rotated log files older than 30 days.

    Expected rotated log file format: fastapi.log.YYYY-MM-DD
    The active log file (fastapi.log) is left untouched.
    """
    cutoff_date = datetime.now() - timedelta(days=30)
    log.info("Starting task: delete_old_logs. Deleting files older than %s.", cutoff_date.date())

    if not os.path.isdir(LOGS_DIR):
        log.warning("Logs directory not found at: %s. Skipping task.", LOGS_DIR)
        return

    for log_file in os.listdir(LOGS_DIR):
        # Skip the active log file
        if log_file == "fastapi.log":
            continue

        # Check for rotated log files that match the expected naming pattern.
        if log_file.startswith("fastapi.log."):
            # Extract the date part after "fastapi.log."
            date_part = log_file.split("fastapi.log.")[-1].strip()
            try:
                log_date = datetime.strptime(date_part, "%Y-%m-%d")
                if log_date < cutoff_date:
                    full_path = os.path.join(LOGS_DIR, log_file)
                    os.remove(full_path)
                    log.info("Deleted old log file: %s", full_path)
            except ValueError:
                # If the date can't be parsed, skip this file.
                log.warning("Could not parse date from log file: %s", log_file)
                continue
    log.info("Finished task: delete_old_logs.")
