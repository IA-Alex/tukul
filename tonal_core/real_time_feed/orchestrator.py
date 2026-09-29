"""Orquestador de consultas a fuentes oficiales.

Coordina el fetch paralelo de múltiples fuentes, la normalización,
el enriquecimiento cruzado y la gestión del caché.

Mismo patrón de red y tolerancia a fallos que `threat_feed.py`:
degradación granular por fuente, solo error si todas fallan.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from articulador_core.logging_config import setup_logging

from .adapters import REGISTRY
from .cache import FeedCache
from .normalizer import FeedNormalizer

logger = setup_logging()


class FeedOrchestrator:
    """Coordina fetch paralelo de fuentes, normalización y caché."""

    def __init__(
        self,
        cache_path: Path,
        ttl_minutes: int = 15,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._cache = FeedCache(cache_path, ttl_minutes)
        self._normalizer = FeedNormalizer()
        self._on_progress = on_progress

    def fetch_all(
        self,
        sources: list[str] | None = None,
        hours: int = 24,
        use_cache: bool = True,
    ) -> list:
        """Consulta múltiples fuentes en paralelo.

        Args:
            sources: IDs de fuentes (None = todas las registradas).
            hours: Ventana temporal.
            use_cache: Si True, respeta TTL del caché.

        Returns:
            Lista de FeedEntry combinadas y ordenadas.

        Raises:
            RuntimeError: si todas las fuentes fallan.
        """
        if sources is None:
            sources = list(REGISTRY.keys())
        if not sources:
            return []

        self._log(f"Consultando {len(sources)} fuentes")

        cached = self._check_cache(sources) if use_cache else {}
        to_fetch = [s for s in sources if s not in cached]
        fresh: dict[str, list] = {}

        if to_fetch:
            fresh = self._fetch_parallel(to_fetch, hours)

        raw_entries: dict[str, list] = {}
        raw_entries.update(cached)
        raw_entries.update(fresh)

        if not raw_entries:
            raise RuntimeError("Ninguna fuente respondió. Verifica tu conexión.")

        # Enriquecer NVD con EPSS y KEV
        nvd = raw_entries.get("nvd", [])
        epss = raw_entries.get("epss", [])
        kev = raw_entries.get("kev", [])
        if nvd and (epss or kev):
            self._log("Enriqueciendo CVEs con EPSS y KEV...")
            raw_entries["nvd"] = self._normalizer.enrich_nvd_with_epss_and_kev(
                nvd, epss, kev
            )

        result = self._normalizer.normalize_all(raw_entries, hours)
        self._log(f"Obtenidas {len(result)} entradas de {len(raw_entries)} fuentes.")
        return result

    def _check_cache(self, sources: list[str]) -> dict[str, list]:
        """Recupera fuentes del caché si están vigentes."""
        cached: dict[str, list] = {}
        for sid in sources:
            entries = self._cache.get(sid)
            if entries is not None:
                cached[sid] = entries
        return cached

    def _fetch_parallel(self, sources: list[str], hours: int) -> dict[str, list]:
        """Ejecuta fetch de fuentes en hilos paralelos."""
        results: dict[str, list] = {}
        errors: dict[str, str] = {}
        lock = threading.Lock()

        def _fetch_one(sid: str) -> None:
            adapter_cls = REGISTRY.get(sid)
            if adapter_cls is None:
                with lock:
                    errors[sid] = f"Adaptador no encontrado: {sid}"
                return
            try:
                self._log(f"  {sid}: consultando...")
                adapter = adapter_cls()
                raw = adapter.fetch(hours)
                entries = adapter.normalize(raw)
                with lock:
                    results[sid] = entries
                self._cache.set(sid, entries)
                self._log(f"  {sid}: {len(entries)} entradas")
            except Exception as error:
                with lock:
                    errors[sid] = str(error)
                logger.warning("FeedOrchestrator: %s falló: %s", sid, error)

        threads = [
            threading.Thread(target=_fetch_one, args=(sid,), daemon=True)
            for sid in sources
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=45)

        if not results and errors:
            detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
            raise RuntimeError(f"Ninguna fuente respondió. {detail}")
        return results

    def _log(self, message: str) -> None:
        if self._on_progress is not None:
            self._on_progress(message)
        logger.info("FeedOrchestrator: %s", message)

    def available_sources(self) -> list[dict[str, str]]:
        """Devuelve la lista de fuentes disponibles para mostrar en UI."""
        return [
            {"id": cls.source_id(), "label": cls.label()}
            for cls in REGISTRY.values()
        ]

    def invalidate_cache(self, source_id: str | None = None) -> None:
        if source_id:
            self._cache.invalidate(source_id)
        else:
            self._cache.clear()
