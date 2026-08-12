from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "articulador"
DEFAULT_LOG_PATH = Path.home() / ".local" / "state" / "articulador" / "articulador.log"
# Motivo del último fallo al instalar el archivo de log, para que el
# diagnóstico pueda explicarlo en vez de limitarse a decir "OK".
_file_handler_error: str = ""


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
    path = log_path or DEFAULT_LOG_PATH

    if logger.handlers:
        # Idempotente, salvo que se pida explícitamente OTRO archivo: antes el
        # parámetro se ignoraba en silencio porque storage.py ya había configurado
        # el logger al importarse, y quien pasaba una ruta nunca la obtenía.
        if log_path is not None:
            _attach_file_handler(logger, path, replace=True)
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Consola (humano-legible)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(StructuredFormatter(is_file=False))
    logger.addHandler(console)

    _attach_file_handler(logger, path)
    return logger


def file_logging_status() -> tuple[bool, str]:
    """Estado real del registro en archivo: (operativo, detalle).

    Comprobar que `logger.debug()` no lanza no dice nada: con el handler de
    consola presente nunca lanza, así que el diagnóstico daba «OK» mientras el
    archivo de log no existía. Aquí se verifica lo que importa: que haya handler
    de archivo y que su destino siga siendo escribible AHORA (el sistema de
    archivos puede pasar a solo lectura después del arranque).
    """
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger(LOGGER_NAME)
    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    if not handlers:
        motivo = _file_handler_error or "no hay archivo de log configurado"
        return False, f"solo consola: {motivo}"

    path = Path(handlers[0].baseFilename)
    try:
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as error:
        return False, f"archivo de log no escribible ({path}): {error}"
    return True, f"OK (archivo: {path})"


def _attach_file_handler(logger: logging.Logger, path: Path, replace: bool = False) -> None:
    """Instala el archivo rotativo. Si no se puede, deja constancia consultable."""
    from logging.handlers import RotatingFileHandler

    global _file_handler_error

    existing = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    if existing and not replace:
        return
    if existing and Path(existing[0].baseFilename) == path.resolve():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
    except OSError as e:
        # Antes era logger.debug() y la consola está en INFO: quedarse sin archivo
        # de log era completamente invisible. Además de avisar, se guarda el
        # motivo para que check_health pueda informar de él.
        _file_handler_error = str(e)
        logger.warning("No se pudo crear el archivo de log en %s: %s", path, e)
        return
    _file_handler_error = ""
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(StructuredFormatter(is_file=True))
    for handler in existing:
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(file_handler)
