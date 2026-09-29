"""Cache local de entradas de fuentes oficiales con TTL.

Persiste las entradas en un archivo JSON junto al estado de la UI,
usando la misma política de escritura atómica que `storage.py`.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tukul_core.logging_config import setup_logging
from tukul_core.models import FeedEntry

logger = setup_logging()

MAX_CACHE_BYTES = 4 * 1024 * 1024  # 4 MB
DEFAULT_TTL_MINUTES = 15


class FeedCache:
    """Cache con TTL para entradas de fuentes oficiales.

    Usa un archivo JSON local con escritura atómica. Las entradas vencidas
    se ignoran silenciosamente y se limpian en la siguiente escritura.
    """

    def __init__(
        self,
        cache_path: Path,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> None:
        self._path = cache_path
        self._ttl = timedelta(minutes=ttl_minutes)
        self._data: dict[str, Any] = self._load()

    def get(self, source_id: str) -> list[FeedEntry] | None:
        """Recupera entradas cacheadas de una fuente si no han vencido."""
        entry = self._data.get(source_id)
        if entry is None:
            return None

        cached_at = entry.get("cached_at", 0)
        if time.time() - cached_at > self._ttl.total_seconds():
            return None

        return self._deserialize_entries(entry.get("entries", []))

    def set(self, source_id: str, entries: list[FeedEntry]) -> None:
        """Almacena entradas en caché con timestamp actual."""
        self._data[source_id] = {
            "cached_at": time.time(),
            "entries": self._serialize_entries(entries),
        }
        self._prune()
        self._save()

    def invalidate(self, source_id: str) -> None:
        """Elimina una fuente específica del caché."""
        self._data.pop(source_id, None)
        self._save()

    def clear(self) -> None:
        """Limpia todo el caché."""
        self._data.clear()
        self._save()

    def _load(self) -> dict[str, Any]:
        """Carga el archivo de caché de forma defensiva."""
        try:
            if self._path.stat().st_size > MAX_CACHE_BYTES:
                logger.warning("FeedCache supera el límite de %d bytes", MAX_CACHE_BYTES)
                return {}
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        """Persiste el caché con escritura atómica."""
        content = json.dumps(self._data, ensure_ascii=False, indent=2) + "\n"
        if len(content.encode("utf-8")) > MAX_CACHE_BYTES:
            logger.warning("FeedCache no se guarda: supera el límite de %d bytes", MAX_CACHE_BYTES)
            return
        self._atomic_write(content)

    def _atomic_write(self, content: str) -> None:
        """Escribe el contenido de forma atómica."""
        tmp = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(self._path)
        except OSError as error:
            logger.warning("FeedCache no pudo escribir: %s", error)

    def _prune(self) -> None:
        """Elimina entradas vencidas y fuentes con entradas vacías."""
        now = time.time()
        expired = [
            sid for sid, entry in self._data.items()
            if now - entry.get("cached_at", 0) > self._ttl.total_seconds()
        ]
        for sid in expired:
            del self._data[sid]

    def _serialize_entries(self, entries: list[FeedEntry]) -> list[dict[str, Any]]:
        """Convierte FeedEntry a dict para JSON."""
        return [
            {
                "source_id": e.source_id,
                "source": e.source,
                "title": e.title,
                "description": e.description,
                "url": e.url,
                "published": e.published.isoformat(),
                "updated": e.updated.isoformat() if e.updated else None,
                "topics": list(e.topics),
                "severity": e.severity,
                "confidence": e.confidence,
                "raw_references": list(e.raw_references),
                "tags": list(e.tags),
            }
            for e in entries
        ]

    def _deserialize_entries(self, raw: list[dict[str, Any]]) -> list[FeedEntry]:
        """Convierte dicts desde JSON a FeedEntry."""
        entries: list[FeedEntry] = []
        for item in raw:
            try:
                published = datetime.fromisoformat(item.get("published", ""))
                updated_raw = item.get("updated")
                updated = datetime.fromisoformat(updated_raw) if updated_raw else None
                entries.append(FeedEntry(
                    source_id=item.get("source_id", ""),
                    source=item.get("source", ""),
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    published=published,
                    updated=updated,
                    topics=tuple(item.get("topics", [])),
                    severity=item.get("severity"),
                    confidence=item.get("confidence", 1.0),
                    raw_references=tuple(item.get("raw_references", [])),
                    tags=frozenset(item.get("tags", [])),
                ))
            except (ValueError, TypeError, KeyError) as error:
                logger.warning("FeedCache: entrada inválida ignorada: %s", error)
                continue
        return entries
