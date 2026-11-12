"""Índice SQLite FTS5 incremental para el corpus local."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from tukul_core.memory.models import IndexStats, MemorySearchResult
from tukul_core.memory.repository import FileMemoryRepository

_QUERY_TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


class CorpusIndex:
    """Mantiene un índice local y determinista de documentos editoriales."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CorpusIndex:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def refresh(self, repository: FileMemoryRepository) -> IndexStats:
        """Actualiza solo archivos nuevos o cuyo tamaño/mtime/hash cambió."""
        connection = self._connection
        documents = list(repository.iter_documents())
        current_paths = {document.relative_path for document in documents}
        indexed = unchanged = 0
        for document in documents:
            row = connection.execute(
                "SELECT size_bytes, modified_ns, content_hash FROM memory_documents "
                "WHERE relative_path = ?",
                (document.relative_path,),
            ).fetchone()
            if row and (
                row["size_bytes"] == document.size_bytes
                and row["modified_ns"] == document.modified_ns
                and row["content_hash"] == document.content_hash
            ):
                unchanged += 1
                continue
            connection.execute(
                "DELETE FROM memory_fts WHERE relative_path = ?",
                (document.relative_path,),
            )
            connection.execute(
                """INSERT INTO memory_documents
                   (relative_path, document_id, title, category, extension,
                    size_bytes, modified_ns, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(relative_path) DO UPDATE SET
                     document_id=excluded.document_id, title=excluded.title,
                     category=excluded.category, extension=excluded.extension,
                     size_bytes=excluded.size_bytes, modified_ns=excluded.modified_ns,
                     content_hash=excluded.content_hash""",
                (document.relative_path, document.document_id, document.title,
                 document.category, document.extension, document.size_bytes,
                 document.modified_ns, document.content_hash),
            )
            connection.execute(
                "INSERT INTO memory_fts(relative_path, title, content, category) "
                "VALUES (?, ?, ?, ?)",
                (document.relative_path, document.title, document.content, document.category),
            )
            indexed += 1

        indexed_paths = {
            row[0] for row in connection.execute("SELECT relative_path FROM memory_documents")
        }
        removed_paths = indexed_paths - current_paths
        for relative_path in removed_paths:
            connection.execute("DELETE FROM memory_fts WHERE relative_path = ?", (relative_path,))
            connection.execute(
                "DELETE FROM memory_documents WHERE relative_path = ?", (relative_path,)
            )
        connection.commit()
        skipped = max(0, len(documents) - indexed - unchanged)
        return IndexStats(len(documents), indexed, unchanged, skipped, len(removed_paths))

    def search(self, query: str, limit: int = 10) -> list[MemorySearchResult]:
        """Busca términos del usuario sin permitir sintaxis FTS arbitraria."""
        if limit < 1 or limit > 100:
            raise ValueError("limit debe estar entre 1 y 100.")
        tokens = _QUERY_TOKEN_RE.findall(query.casefold())
        if not tokens:
            return []
        match_query = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
        rows = self._connection.execute(
            """SELECT d.document_id, d.relative_path, d.title, d.category,
                      bm25(memory_fts) AS rank, memory_fts.content
               FROM memory_fts
               JOIN memory_documents d USING(relative_path)
               WHERE memory_fts MATCH ?
               ORDER BY rank, d.relative_path
               LIMIT ?""",
            (match_query, limit),
        ).fetchall()
        return [
            MemorySearchResult(
                document_id=row["document_id"],
                relative_path=row["relative_path"],
                title=row["title"],
                category=row["category"],
                score=float(-row["rank"]),
                excerpt=_excerpt(row["content"], tokens),
            )
            for row in rows
        ]

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_documents (
                relative_path TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                extension TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL,
                content_hash TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                relative_path UNINDEXED,
                title,
                content,
                category
            );
            """
        )
        self._connection.commit()


def _excerpt(content: str, tokens: list[str], radius: int = 180) -> str:
    """Devuelve un fragmento legible alrededor del primer término encontrado."""
    lowered = content.casefold()
    position = min((lowered.find(token) for token in tokens if lowered.find(token) >= 0), default=0)
    start = max(0, position - radius)
    end = min(len(content), position + radius)
    excerpt = " ".join(content[start:end].split())
    return ("…" if start else "") + excerpt + ("…" if end < len(content) else "")
