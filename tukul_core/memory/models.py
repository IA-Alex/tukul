"""Modelos inmutables para el corpus de memoria local."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryDocument:
    """Documento indexable y su contenido ya validado como texto."""

    document_id: str
    relative_path: str
    title: str
    category: str
    extension: str
    size_bytes: int
    modified_ns: int
    content_hash: str
    content: str


@dataclass(frozen=True)
class MemorySearchResult:
    """Resultado trazable de una búsqueda del corpus."""

    document_id: str
    relative_path: str
    title: str
    category: str
    score: float
    excerpt: str


@dataclass(frozen=True)
class IndexStats:
    """Resultado de una actualización del índice."""

    scanned: int
    indexed: int
    unchanged: int
    skipped: int
    removed: int
