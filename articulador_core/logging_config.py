from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "articulador"


class StructuredFormatter(logging.Formatter):
    """Formatter que produce JSON para archivo, texto simple para consola."""

    def __init__(self, is_file: bool = False):
        self.is_file = is_file
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        """Genera log estructurado o simple."""
        if self.is_file:
            # JSON para archivo (máquina-legible)
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }
            if record.exc_info:
                log_entry["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_entry, ensure_ascii=False)
        else:
            # Texto simple para consola (humano-legible)
            emoji = {"INFO": "ℹ️ ", "WARNING": "⚠️ ", "ERROR": "❌", "DEBUG": "🔍", "CRITICAL": "🚨"}.get(record.levelname, "•")
            return f"{emoji} {record.getMessage()}"


def setup_logging(log_path: Path | None = None) -> logging.Logger:
    """Configura logging estructurado con soporte para archivo rotativo.

    Archivo:
    - Ubicación: ~/.local/state/articulador/articulador.log
    - Formato: JSON (máquina-legible para análisis)
    - Rotación: 512KB x 2 backups
    - Nivel: INFO+

    Consola:
    - Formato: emoji + texto
    - Nivel: INFO+

    Características:
    - Sin incluir API keys ni contenido sensible
    - Thread-safe
    - No includes de respuestas del modelo
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Consola (humano-legible)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(StructuredFormatter(is_file=False))
    logger.addHandler(console)

    # Archivo (máquina-legible)
    try:
        from logging.handlers import RotatingFileHandler

        path = log_path or Path.home() / ".local" / "state" / "articulador" / "articulador.log"
        path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            path, maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter(is_file=True))
        logger.addHandler(file_handler)
    except OSError as e:
        logger.debug(f"No se pudo crear archivo de log: {e}")

    return logger
