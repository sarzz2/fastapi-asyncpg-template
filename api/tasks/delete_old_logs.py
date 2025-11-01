import logging
import os
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LOGS_DIR = "../../logs"


def delete_old_logs() -> None:
    """
    Deletes rotated log files older than 30 days.

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
                    logging.info("Deleted old log file: %s", full_path)
            except ValueError:
                # If the date can't be parsed, skip this file.
                logging.warning("Could not parse date from log file: %s", log_file)
                continue
