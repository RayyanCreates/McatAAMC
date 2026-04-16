"""
logger_util.py — Logging setup for the MCAT Question Generator add-on.

Writes logs to ~/.mcat_qgen.log at all times so the log is always
reachable without needing a profile to be open.

No aqt imports here — this module must be importable at the very first
line of __init__.py, before Anki has finished initialising.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_logger: Optional[logging.Logger] = None
LOGGER_NAME = "mcat_question_generator"

# Fixed log path — always writable, no aqt dependency needed
_LOG_PATH = os.path.join(os.path.expanduser("~"), ".mcat_qgen.log")


def setup_logging() -> None:
    """
    Configure the add-on logger.  Safe to call multiple times; only
    initialises once.  Must not import from aqt.
    """
    global _logger
    if _logger is not None:
        return

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Don't pollute the root Anki logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(module)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Try file handler first; fall back to stderr
    try:
        handler: logging.Handler = logging.FileHandler(
            _LOG_PATH, encoding="utf-8", delay=True
        )
    except Exception:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Also mirror to stderr so the message appears in Anki's output pane
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)  # only warnings+ to stderr
    logger.addHandler(stderr_handler)

    _logger = logger


def get_logger() -> logging.Logger:
    """Return the add-on logger, initialising it if necessary."""
    if _logger is None:
        setup_logging()
    # _logger is guaranteed non-None after setup_logging()
    return _logger  # type: ignore[return-value]
