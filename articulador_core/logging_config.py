from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "articulador"


def setup_logging(log_path: Path | None = None) -> logging.Logger:
    """Configura un registro local rotativo sin incluir contenido ni API keys."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler: logging.Handler
    try:
        from logging.handlers import RotatingFileHandler
        path = log_path or Path.home() / ".local" / "state" / "articulador" / "articulador.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=512_000, backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger
