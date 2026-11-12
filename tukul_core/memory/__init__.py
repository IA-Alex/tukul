"""Memoria local de documentos editoriales.

La capa de memoria solo lee archivos autorizados y devuelve resultados trazables.
No ejecuta contenido del corpus ni decide por sí sola qué se envía a un LLM.
"""

from tukul_core.memory.index import CorpusIndex, IndexStats
from tukul_core.memory.models import MemoryDocument, MemorySearchResult
from tukul_core.memory.policy import MemoryPolicy
from tukul_core.memory.repository import FileMemoryRepository

__all__ = [
    "CorpusIndex",
    "FileMemoryRepository",
    "IndexStats",
    "MemoryDocument",
    "MemoryPolicy",
    "MemorySearchResult",
]
