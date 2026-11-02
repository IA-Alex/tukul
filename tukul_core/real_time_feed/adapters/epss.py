"""Adaptador para EPSS (Exploit Prediction Scoring System) de FIRST.org.

Proporciona scores de probabilidad de explotación para CVEs.
Se usa como fuente complementaria para enriquecer entradas de NVD.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from tukul_core.http_safety import NO_REDIRECT_OPENER
from tukul_core.models import FeedEntry

from .base import SourceAdapter

EPSS_ENDPOINT = "https://api.first.org/data/v1/epss"
HTTP_TIMEOUT = 30
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_MAX = 4.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
USER_AGENT = "Tukul/ThreatFeed (+https://github.com/; contacto: mantenedor del repositorio)"


class EpssAdapter(SourceAdapter):
    """Consulta scores EPSS para CVEs específicos."""

    @classmethod
    def source_id(cls) -> str:
        return "epss"

    @classmethod
    def label(cls) -> str:
        return "FIRST EPSS (Exploit Prediction Scoring System)"

    def fetch(self, hours: int, cve_ids: list[str] | None = None) -> list[dict]:
        """Obtiene scores EPSS recientes.

        Args:
            hours: Ventana temporal (se ignora; EPSS devuelve datos del día más reciente).
            cve_ids: Lista opcional de CVE IDs para filtrar. Si se proporciona,
                     solo se devuelven scores para esos CVEs.

        Nota: EPSS no tiene filtro por fecha directo. Este adaptador
        devuelve los scores más recientes disponibles. El orquestador
        combina estos scores con las entradas de NVD.
        """
        url = f"{EPSS_ENDPOINT}?date={datetime.now(UTC).strftime('%Y-%m-%d')}"
        if cve_ids:
            params = urllib.parse.urlencode([("cve", cve) for cve in cve_ids])
            url = f"{EPSS_ENDPOINT}?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                data = json.loads(self._read_bounded(response))
                return list(data.get("data", []))
            except urllib.error.HTTPError as error:
                if error.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    self._sleep(error, attempt)
                    continue
                raise RuntimeError(f"EPSS respondió {error.code}: {error.reason}") from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(f"No se pudo conectar con EPSS: {error.reason}") from error
            except (TimeoutError, OSError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(f"No se pudo conectar con EPSS: {error}") from error

        raise RuntimeError("No se pudo obtener datos de EPSS tras los reintentos.")

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte scores EPSS en FeedEntry (enriquecimiento).

        Estos entries no tienen descripción propia; sirven para
        complementar entries de NVD con la probabilidad de explotación.
        """
        entries: list[FeedEntry] = []
        for item in raw:
            cve_id = item.get("cve", "")
            if not cve_id:
                continue
            epss_str = item.get("epss", "0")
            try:
                epss_score = float(epss_str)
            except (ValueError, TypeError):
                epss_score = 0.0

            tags = {"epss", "cve"}
            if epss_score > 0.9:
                tags.add("alta_probabilidad_explotacion")

            entries.append(FeedEntry(
                source_id=f"epss:{cve_id}",
                source="epss",
                title=f"EPSS {cve_id}",
                description=f"Probabilidad de explotación: {epss_score:.4f}",
                url=f"https://api.first.org/data/v1/epss?cve={cve_id}",
                published=datetime.now(UTC),
                severity=epss_score * 10,  # Normalizar a escala 0-10
                confidence=0.8,
                topics=("ciberseguridad", "cve", "epss"),
                tags=frozenset(tags),
            ))
        return entries

    def _read_bounded(self, response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("La respuesta de EPSS supera el límite de bytes.")
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
        jitter = delay * 0.25 * random.random()
        delay = min(delay + jitter, BACKOFF_MAX * 1.25)
        time.sleep(delay)
