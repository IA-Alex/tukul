"""Gestiona persistencia y estado de documentos."""
from __future__ import annotations

from pathlib import Path

from tukul_core import storage
from tukul_core.autosave import clear_autosave
from tukul_core.models import ArticleSession

# Tope de lectura: un artículo de texto es una pieza editorial, no un volcado de
# datos. `read_text()` carga el archivo entero en memoria; sin este límite, abrir
# un archivo inmenso congela o agota la RAM del editor antes de poder reaccionar.
MAX_ARTICLE_BYTES = 5 * 1024 * 1024


def _read_bounded(path: Path) -> str:
    """Lee un archivo de texto con tope de tamaño. Lanza si no cabe.

    El tamaño se comprueba con `stat()` antes de leer, para no consumir el
    contenido en vano. Levanta ValueError si supera `MAX_ARTICLE_BYTES`; los
    errores de E/S y de codificación los propaga tal cual.
    """
    size = path.stat().st_size
    if size > MAX_ARTICLE_BYTES:
        raise ValueError(
            f"El archivo pesa {size:,} bytes y supera el límite de "
            f"{MAX_ARTICLE_BYTES // (1024 * 1024)} MB."
        )
    return path.read_text(encoding="utf-8")


class DocumentManager:
    """Maneja carga, guardado y estado de documentos."""

    def __init__(self) -> None:
        self.session = ArticleSession()

    def set_session(self, session: ArticleSession) -> None:
        """Reemplaza la sesión actual."""
        self.session = session

    def open_document(self, path: Path) -> tuple[bool, str, ArticleSession]:
        """Carga un documento. Retorna (éxito, error_msg, sesión)."""
        try:
            content = _read_bounded(path)
            session = ArticleSession(
                document_path=path.resolve(),
                article=content
            )
            return True, "", session
        except (OSError, UnicodeError, ValueError) as error:
            return False, str(error), self.session

    def save_document(self, session: ArticleSession) -> tuple[bool, str]:
        """Guarda documento de forma atómica. Retorna (éxito, error_msg)."""
        if session.document_path is None:
            return False, "Guarda primero el artículo Markdown."

        try:
            # atomic_write garantiza consistencia (no corrupciones parciales).
            storage.atomic_write(session.document_path, session.article)
            session.dirty = False
            # El guardado limpio deja obsoleto cualquier respaldo de recuperación.
            clear_autosave(session.document_path)
            return True, ""
        except (OSError, UnicodeEncodeError) as error:
            return False, str(error)

    def open_project(self, path: Path) -> tuple[bool, str, ArticleSession]:
        """Carga proyecto. Retorna (éxito, error_msg, sesión)."""
        try:
            data = storage.load_project(path)
            document = Path(data["document"])

            if not document.is_file():
                return False, f"No existe el artículo del proyecto: {document}", self.session

            article = _read_bounded(document)
            session = ArticleSession(
                document_path=document,
                project_path=path,
                article=article,
                conversation=data.get("conversation", []),
            )
            return True, "", session
        except (OSError, ValueError, UnicodeError) as error:
            return False, str(error), self.session

    def save_project(self, session: ArticleSession, path: Path) -> tuple[bool, str]:
        """Guarda proyecto. Retorna (éxito, error_msg)."""
        if session.document_path is None:
            return False, "Guarda primero el artículo Markdown."

        try:
            storage.save_project(session, path)
            return True, ""
        except (OSError, ValueError, RuntimeError) as error:
            # ValueError: el artículo no cuelga de la carpeta del proyecto.
            # RuntimeError: falta tomli-w. Ambos deben llegar al usuario como texto,
            # no escapar hasta el manejador global de excepciones de Tk.
            return False, str(error)
