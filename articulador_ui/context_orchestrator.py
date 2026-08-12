"""Gestiona indexación y selección de contexto local."""
from __future__ import annotations

from pathlib import Path

from articulador_core.context import ContextIndex
from articulador_core.logging_config import setup_logging

logger = setup_logging()


class ContextOrchestrator:
    """Orquesta indexación de archivos y selección de contexto."""

    def __init__(self, workspace_root: Path) -> None:
        self.index = ContextIndex(workspace_root)
        self.excluded_context: set[str] = set()
        self.last_context_files: list[str] = []

    def prepare_context(
        self, query: str, max_chars: int
    ) -> tuple[bool, str, list[str]]:
        """Prepara contexto para una consulta. Retorna (éxito, packet, files)."""
        try:
            packet, files = self.index.packet(query, max_chars, self.excluded_context)
            self.last_context_files = files
            return True, packet, files
        except Exception as error:
            logger.error("Error preparando contexto: %s", error, exc_info=error)
            return False, "", []

    def exclude_file(self, filename: str) -> None:
        """Excluye archivo del contexto futuro."""
        self.excluded_context.add(filename)

    def include_file(self, filename: str) -> None:
        """Incluye archivo en el contexto."""
        self.excluded_context.discard(filename)

    def get_last_reasons(self) -> dict[str, str]:
        """Retorna razones de selección del último contexto."""
        return self.index.last_reasons
