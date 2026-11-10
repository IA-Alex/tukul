"""Adaptador para la National Vulnerability Database (NVD) API v2.

Reimplementa el fetch de `threat_feed.py` como un `SourceAdapter`.
La lógica de red (timeout, reintentos, backoff, techo de bytes) es idéntica.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from tukul_core.http_safety import NO_REDIRECT_OPENER
from tukul_core.models import FeedEntry

from .base import SourceAdapter

NVD_ENDPOINT = "https://services.nvd.nist.gov/rest/json/cves/2.0"
HTTP_TIMEOUT = 30
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_MAX = 4.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
USER_AGENT = "Tukul/ThreatFeed (+https://github.com/; contacto: mantenedor del repositorio)"


class NvdAdapter(SourceAdapter):
    """Consulta CVEs recientes desde la NVD API v2."""

    @classmethod
    def source_id(cls) -> str:
        return "nvd"

    @classmethod
    def label(cls) -> str:
        return "National Vulnerability Database (NVD)"

    def fetch(self, hours: int) -> list[dict]:
        """Obtiene CVEs publicados en las últimas N horas."""
        if hours <= 0:
            raise RuntimeError("La ventana temporal debe ser positiva.")

        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        params = urllib.parse.urlencode({
            "pubStartDate": since,
            "pubEndDate": datetime.now(UTC).isoformat(),
            "resultsPerPage": 100,
        })
        url = f"{NVD_ENDPOINT}?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                data = json.loads(self._read_bounded(response))
                return list(data.get("vulnerabilities", []))
            except urllib.error.HTTPError as error:
                if error.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    self._sleep(error, attempt)
                    continue
                raise RuntimeError(f"NVD respondió {error.code}: {error.reason}") from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(f"No se pudo conectar con NVD: {error.reason}") from error
            except (TimeoutError, OSError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(f"No se pudo conectar con NVD: {error}") from error

        raise RuntimeError("No se pudo obtener datos de NVD tras los reintentos.")

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte vulnerabilidades crudas de NVD en FeedEntry."""
        entries: list[FeedEntry] = []
        for vuln in raw:
            cve = vuln.get("cve", {})
            cve_id = cve.get("id", "")
            if not cve_id:
                continue

            published = _parse_nvd_date(cve.get("published", ""))
            descriptions = cve.get("descriptions", [])
            description = next(
                (d["value"] for d in descriptions if d.get("lang") == "en"),
                "",
            )
            refs: tuple[str, ...] = tuple(
                r["url"] for r in cve.get("references", []) if "url" in r
            )

            cvss_score: float | None = None
            metrics = cve.get("metrics", {})
            for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                metric_list = metrics.get(key, [])
                if metric_list:
                    cvss_score = metric_list[0].get("cvssData", {}).get("baseScore")
                    break

            topics: tuple[str, ...] = ("ciberseguridad", "cve")
            tags = {"cve", "nvd"}
            if cvss_score is not None and cvss_score >= 7.0:
                tags.add("alta_criticidad")
                topics = ("ciberseguridad", "cve", "alta_criticidad")

            entries.append(FeedEntry(
                source_id=f"nvd:{cve_id}",
                source="nvd",
                title=cve_id,
                description=description,
                url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                published=published,
                severity=cvss_score,
                raw_references=refs,
                topics=topics,
                tags=frozenset(tags),
            ))
        return entries

    def _read_bounded(self, response: Any) -> bytes:
        """Lee la respuesta con techo de bytes."""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("La respuesta de NVD supera el límite de bytes.")
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


def _parse_nvd_date(raw: str) -> datetime:
    """Parsea fecha ISO de NVD."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(UTC)
