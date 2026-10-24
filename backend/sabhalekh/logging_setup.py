"""Rolling log files in DATA_DIR/logs (5 x 5 MB) plus stderr."""
from __future__ import annotations

import logging
import logging.handlers

from . import config


def setup(level: str = "INFO") -> None:
    config.ensure_dirs()
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(config.LOGS_DIR / "backend.log", maxBytes=5 * 1024 * 1024,
                                              backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    for noisy in ("faster_whisper", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
