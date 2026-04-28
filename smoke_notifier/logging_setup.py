"""
Logging setup — configure console + rotating file handlers.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(config):
    """Configure logging with console output and rotating file handler."""
    fmt     = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    log_dir = os.path.dirname(config.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            config.log_file,
            maxBytes=config.log_max_size_mb * 1024 * 1024,
            backupCount=config.log_backup_count,
        ),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )
