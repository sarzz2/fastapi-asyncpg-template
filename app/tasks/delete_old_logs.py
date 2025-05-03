import os
from datetime import datetime, timedelta

from celery import shared_task

LOGS_DIR = "./logs"


@shared_task
def delete_old_logs():
    """Deletes rotated log files older than 30 days.

    Expected rotated log file format: fastapi.log.YYYY-MM-DD
    The active log file (fastapi.log) is left untouched.
    """
    cutoff_date = datetime.now() - timedelta(days=30)

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
                    print(f"Deleted old log file: {full_path}")
            except ValueError:
                # If the date can't be parsed, skip this file.
                print(f"Could not parse date from log file: {log_file}")
                continue
