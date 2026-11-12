"""Orquestador de consultas a fuentes oficiales.

Coordina el fetch paralelo de múltiples fuentes, la normalización,
el enriquecimiento cruzado y la gestión del caché.

Mismo patrón de red y tolerancia a fallos que `threat_feed.py`:
degradación granular por fuente, solo error si todas fallan.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path

from tukul_core.logging_config import setup_logging

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

        # EPSS se consulta por CVE: pedirlo sin la lista devuelve 100 filas
        # arbitrarias del día que casi nunca cruzan con los CVE de NVD, así que
        # el enriquecimiento quedaba en no-op. Se re-consulta acotado a los CVE
        # realmente obtenidos de NVD.
        raw_entries = self._recover_epss_for_nvd(raw_entries, hours)

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

    def _recover_epss_for_nvd(self, raw_entries: dict[str, list], hours: int) -> dict[str, list]:
        """Re-consulta EPSS acotado a los CVE de NVD y sustituye la fuente.

        `FeedOrchestrator` llama `fetch(hours)` a todas las fuentes por igual,
        pero EPSS responde por CVE: sin la lista devuelve una muestra arbitraria
        del día. Aquí, ya con los CVE de NVD en mano, se pide EPSS solo para
        esos IDs (mismo mecanismo que `threat_feed.fetch_epss`). Si EPSS no
        estaba entre las fuentes, no se introduce; si falla, la degradación es
        granular y se conserva lo que hubiera.
        """
        if "epss" not in raw_entries:
            return raw_entries
        cve_ids = _cve_ids_de(raw_entries.get("nvd", []))
        if not cve_ids:
            return raw_entries
        adapter_cls = REGISTRY.get("epss")
        if adapter_cls is None:
            return raw_entries
        # Troceado en lotes como `threat_feed.fetch_epss`: una query string con
        # cientos de CVE es frágil y un lote caído no debe tumbar los demás.
        self._log(f"  epss: re-consultando {len(cve_ids)} CVE de NVD...")
        entries: list = []
        fallos = 0
        for i in range(0, len(cve_ids), EPSS_BATCH_SIZE):
            lote = cve_ids[i:i + EPSS_BATCH_SIZE]
            try:
                adapter = adapter_cls()
                raw = adapter.fetch(hours, cve_ids=lote)
                entries.extend(adapter.normalize(raw))
            except Exception as error:
                fallos += 1
                logger.warning(
                    "FeedOrchestrator: EPSS dirigido por CVE falló (lote %d): %s",
                    i // EPSS_BATCH_SIZE, error,
                )
        if not entries and fallos:
            # Ningún lote respondió: se conserva la fuente previa (degradación
            # granular) en vez de dejarla vacía.
            return raw_entries
        raw_entries["epss"] = entries
        self._cache.set("epss", entries)
        self._log(f"  epss: {len(entries)} entradas acotadas a NVD")
        return raw_entries

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


# EPSS acepta lotes por query string; se trocea como en `threat_feed.fetch_epss`
# para no construir URLs frágiles con cientos de CVE.
EPSS_BATCH_SIZE = 100

_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")


def _cve_ids_de(entries: list) -> list[str]:
    """Extrae los CVE IDs válidos de las entradas NVD (source_id `nvd:CVE-…`)."""
    ids: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        cve_id = str(getattr(entry, "source_id", "")).replace("nvd:", "", 1)
        if _CVE_RE.match(cve_id) and cve_id not in seen:
            seen.add(cve_id)
            ids.append(cve_id)
    return ids
