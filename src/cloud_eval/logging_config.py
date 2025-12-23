from __future__ import annotations

import logging
import os


class _CloudEvalFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("cloud_eval"):
            return True
        return record.levelno >= logging.WARNING


def configure_logging() -> None:
    """Initialize logging using the configured log level."""
    level_name = os.getenv("CLOUD_EVAL_LOG_LEVEL", "").strip()
    if level_name:
        try:
            root_level = getattr(logging, level_name.upper())
        except AttributeError:
            root_level = logging.INFO
    else:
        enable_debug = os.getenv("CLOUD_EVAL_DEBUG", "").lower() in {"1", "true", "yes"}
        root_level = logging.DEBUG if enable_debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setLevel(root_level)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_CloudEvalFilter())

    root = logging.getLogger()
    root.handlers[:] = []
    handler.setLevel(root_level)
    root.addHandler(handler)
    root.setLevel(root_level)
