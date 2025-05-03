import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from queue import Queue
from threading import Thread

import colorlog

# Define the directory and file for FastAPI logs.
LOG_DIR = "logs"

# Create the log directory if it doesn't exist.
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Set the log file name to "fastapi.log".
log_file_name = f"{LOG_DIR}/fastapi.log"


def configure_logging():
    logger = logging.getLogger("fastapi")
    # Clear existing handlers for uvicorn.access to avoid duplicate logging.
    logging.getLogger("uvicorn.access").handlers.clear()
    logger.setLevel(logging.DEBUG)

    # Create a queue for logging.
    log_queue = Queue()

    # Create the console handler to output logs to stdout.
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)s:     %(message)s",
        log_colors={
            "DEBUG": "bold_blue",
            "INFO": "bold_green",
            "WARNING": "bold_yellow",
            "ERROR": "bold_red",
            "CRITICAL": "bold_purple",
        },
    )
    console_handler.setFormatter(console_formatter)

    # Create a file handler that rotates at midnight.
    file_handler = TimedRotatingFileHandler(log_file_name, when="midnight", interval=1, backupCount=365)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    # Use a queue handler to avoid blocking the main thread.
    log_queue_handler = logging.handlers.QueueHandler(log_queue)
    logger.addHandler(log_queue_handler)

    # Set up uvicorn.access logging if needed.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.DEBUG)

    # Start a listener thread that processes log records from the queue.
    def listener():
        while True:
            record = log_queue.get()
            if record is None:
                break
            # Send the log record to both the console and file handlers.
            console_handler.handle(record)
            file_handler.handle(record)

    listener_thread = Thread(target=listener, daemon=True)
    listener_thread.start()

    return logger
