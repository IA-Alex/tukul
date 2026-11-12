"""Adaptador para el catálogo CISA Known Exploited Vulnerabilities (KEV).

Proporciona la lista de vulnerabilidades que CISA ha confirmado como
explotadas activamente. Se usa para enriquecer entradas de NVD con la
etiqueta KEV.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from tukul_core.http_safety import NO_REDIRECT_OPENER
from tukul_core.models import FeedEntry

from .base import SourceAdapter

KEV_ENDPOINT = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
HTTP_TIMEOUT = 30
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_MAX = 4.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
USER_AGENT = "Tukul/ThreatFeed (+https://github.com/; contacto: mantenedor del repositorio)"


class KevAdapter(SourceAdapter):
    """Obtiene el catálogo CISA KEV completo."""

    @classmethod
    def source_id(cls) -> str:
        return "kev"

    @classmethod
    def label(cls) -> str:
        return "CISA Known Exploited Vulnerabilities (KEV)"

    def fetch(self, hours: int, **kwargs: Any) -> list[dict]:
        """Obtiene el catálogo KEV completo.

        KEV no tiene filtro por fecha en el endpoint; se devuelve entero
        y el normalizador filtra por ventana temporal si es necesario.
        """
        request = urllib.request.Request(KEV_ENDPOINT, headers={"User-Agent": USER_AGENT})

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                data = json.loads(self._read_bounded(response))
                return list(data.get("vulnerabilities", []))
            except urllib.error.HTTPError as error:
                if error.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    self._sleep(error, attempt)
                    continue
                raise RuntimeError(f"CISA KEV respondió {error.code}: {error.reason}") from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(f"No se pudo conectar con CISA KEV: {error.reason}") from error
            except (TimeoutError, OSError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(f"No se pudo conectar con CISA KEV: {error}") from error

        raise RuntimeError("No se pudo obtener datos de CISA KEV tras los reintentos.")

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte entradas KEV en FeedEntry para enriquecimiento."""
        entries: list[FeedEntry] = []
        for vuln in raw:
            cve_id = vuln.get("cveID", "")
            if not cve_id:
                continue

            description = vuln.get("shortDescription", "")
            date_added = vuln.get("dateAdded", "")
            try:
                # `dateAdded` llega como fecha sin hora ("2026-11-10"):
                # `fromisoformat` produce un datetime NAIVE y `normalize_all`
                # lo compara contra un `since` aware → TypeError que tumbaba
                # TODO el pipeline de ideas. Se fija UTC, igual que el resto
                # de adaptadores (NVD/EPSS/arXiv/MITRE).
                published = datetime.fromisoformat(date_added).replace(tzinfo=UTC)
            except (ValueError, TypeError):
                published = datetime.now(UTC)

            entries.append(FeedEntry(
                source_id=f"kev:{cve_id}",
                source="kev",
                title=f"KEV {cve_id}",
                description=description,
                url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                published=published,
                severity=None,
                confidence=0.95,  # CISA KEV es fuente de alta confianza
                topics=("ciberseguridad", "cve", "kev"),
                tags=frozenset({"kev", "cve", "explotacion_activa"}),
            ))
        return entries

    def _read_bounded(self, response: Any) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("La respuesta de CISA KEV supera el límite de bytes.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _sleep(self, error: urllib.error.HTTPError | None, attempt: int) -> None:
        """Backoff exponencial con jitter (0-25 % aleatorio)."""
        delay = BACKOFF_BASE * (2 ** (attempt - 1))
        if error is not None and error.code == 429:
            retry_after = error.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = min(int(retry_after), BACKOFF_MAX)
                except (ValueError, TypeError):
                    pass
        jitter = delay * 0.25 * random.random()  # nosec B311 - jitter de backoff, no criptográfico
        delay = min(delay + jitter, BACKOFF_MAX * 1.25)
        time.sleep(delay)
