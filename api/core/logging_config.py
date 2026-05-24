import logging
import re
import sys
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from typing import Any

import colorlog
from pythonjsonlogger import json

from api.core.config import settings
from api.core.context import APP_BUILD, APP_VERSION, CLIENT_REGION, DEVICE_ID, PLATFORM


class ContextualFilter(logging.Filter):
    """
    Filter to inject context variables into log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.app_version = APP_VERSION.get() or "N/A"
        record.app_build = APP_BUILD.get() or "N/A"
        record.platform = PLATFORM.get() or "N/A"
        record.device_id = DEVICE_ID.get() or "N/A"
        record.client_region = CLIENT_REGION.get() or "N/A"
        return True


class ColoredJsonFormatter(json.JsonFormatter):
    """
    Custom JSON formatter that adds indentation and colors for console output.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.is_console = kwargs.pop("is_console", False)
        super().__init__(*args, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        # Save original levelname to restore later
        orig_levelname = record.levelname

        # Define colors for levels
        colors = {
            "DEBUG": "\033[94m",  # Blue
            "INFO": "\033[92m",  # Green
            "WARNING": "\033[93m",  # Yellow
            "ERROR": "\033[91m",  # Red
            "CRITICAL": "\033[1;95m",  # Bold Purple
        }
        color = colors.get(orig_levelname, "")

        if self.is_console:
            record.levelname = f"{color}{orig_levelname}\033[0m"

        # Generate JSON string using the base class logic
        json_str = super().format(record)

        # Restore original levelname for other handlers
        record.levelname = orig_levelname

        if self.is_console and color:
            # 1. Color the JSON keys in Cyan
            json_str = re.sub(r'(".*?"):', r"\033[1;36m\1\033[0m:", json_str)

            # 2. Color the values based on the log level
            # This regex matches the value part after the colon and applies the level color
            # It handles strings, numbers, booleans, and nulls
            json_str = re.sub(r':\s*(".*?"|\d+\.?\d*|true|false|null)', f": {color}\\1\033[0m", json_str)

        return json_str


def configure_logging() -> logging.Logger:
    """
    Configure logging for the FastAPI application.
    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger("fastapi")
    # Clear existing handlers for uvicorn.access to avoid duplicate logging.
    logger.propagate = False
    logging.getLogger("uvicorn.access").handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.addFilter(ContextualFilter())

    # Create the console handler to output logs to stdout.
    console_handler = logging.StreamHandler(sys.stdout)

    if settings.USE_JSON_LOGS:
        log_format = (
            "%(asctime)s %(levelname)s %(message)s %(name)s %(module)s "
            "%(funcName)s %(lineno)d %(app_version)s %(app_build)s %(platform)s %(device_id)s %(client_region)s"
        )
        # Use colored and indented formatter for console
        formatter: logging.Formatter = ColoredJsonFormatter(
            log_format,
            is_console=True,
            json_indent=4 if settings.ENV != "prod" else None,
        )
        console_handler.setFormatter(formatter)
    else:
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(levelname)s:     %(message)s",
            log_colors={
                "DEBUG": "bold_blue",
                "INFO": "bold_green",
                "WARNING": "bold_yellow",
                "ERROR": "bold_red",
                "CRITICAL": "bold_purple",
            },
        )
        console_handler.setFormatter(formatter)

    # Create a queue for async logging.
    log_queue: Queue = Queue()
    log_queue_handler = QueueHandler(log_queue)
    logger.addHandler(log_queue_handler)

    # Set up uvicorn.access logging if needed.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.DEBUG)
    access_logger.addFilter(ContextualFilter())
    access_logger.addHandler(log_queue_handler)
    access_logger.propagate = False

    # Start the native QueueListener to handle queue records on a background thread.
    listener = QueueListener(log_queue, console_handler)
    listener.start()

    return logger
