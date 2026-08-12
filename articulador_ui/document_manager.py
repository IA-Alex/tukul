"""Gestiona persistencia y estado de documentos."""
from __future__ import annotations

from pathlib import Path

from articulador_core import storage
from articulador_core.models import ArticleSession


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
            content = path.read_text(encoding="utf-8")
            session = ArticleSession(
                document_path=path.resolve(),
                article=content
            )
            return True, "", session
        except (OSError, UnicodeError) as error:
            return False, str(error), self.session

    def save_document(self, session: ArticleSession) -> tuple[bool, str]:
        """Guarda documento de forma atómica. Retorna (éxito, error_msg)."""
        if session.document_path is None:
            return False, "Guarda primero el artículo Markdown."

        try:
            # Usar _atomic_write para garantizar consistencia (no corrupciones parciales)
            storage._atomic_write(session.document_path, session.article)
            session.dirty = False
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

            article = document.read_text(encoding="utf-8")
            session = ArticleSession(
                document_path=document,
                project_path=path,
                article=article,
                corpus_path=data.get("corpus"),
                evidence=list(data.get("evidence", [])),
                conversation=data.get("conversation", []),
            )
            return True, "", session
        except (OSError, ValueError) as error:
            return False, str(error), self.session

    def save_project(self, session: ArticleSession, path: Path) -> tuple[bool, str]:
        """Guarda proyecto. Retorna (éxito, error_msg)."""
        if session.document_path is None:
            return False, "Guarda primero el artículo Markdown."

        try:
            storage.save_project(session, path)
            return True, ""
        except OSError as error:
            return False, str(error)
