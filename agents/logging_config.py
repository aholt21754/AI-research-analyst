import logging
import os
from pythonjsonlogger import json as jsonlogger


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Already configured

    level = logging.DEBUG if os.getenv("ENV", "local") == "local" else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
