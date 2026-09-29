"""Respaldo de recuperación ante cierres abruptos (autosave).

El artículo se guarda a intervalos en un directorio de estado del usuario, lejos
del workspace, para que un corte de luz o un cierre forzado no se lleve el texto
sin guardar. El respaldo se escribe solo mientras el documento está sucio y se
borra en cuanto hay un guardado limpio o una decisión explícita de cerrar.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .logging_config import setup_logging
from .storage import atomic_write

logger = setup_logging()

AUTOSAVE_DIR = Path.home() / ".local" / "state" / "articulador" / "autosave"


def _autosave_path(document_path: Path) -> Path:
    """Ruta determinista del respaldo de un documento, ajena al workspace."""
    digest = hashlib.sha256(str(document_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return AUTOSAVE_DIR / f"{document_path.name}.{digest}.md"


def write_autosave(document_path: Path, content: str) -> None:
    """Escribe el respaldo de recuperación de un documento.

    Es best-effort: si el directorio de estado no es escribible, el respaldo
    sencillamente no se guarda y se deja constancia en el log, sin interrumpir
    la escritura principal.
    """
    try:
        atomic_write(_autosave_path(document_path), content)
    except OSError as error:
        logger.warning("No se pudo escribir el autosave de %s: %s", document_path, error)


def read_autosave(document_path: Path) -> str | None:
    """Contenido del respaldo si existe; None en caso contrario."""
    try:
        return _autosave_path(document_path).read_text(encoding="utf-8")
    except OSError:
        return None


def clear_autosave(document_path: Path) -> None:
    """Borra el respaldo: el documento se guardó limpio o se decidió cerrar."""
    try:
        _autosave_path(document_path).unlink(missing_ok=True)
    except OSError:
        pass
