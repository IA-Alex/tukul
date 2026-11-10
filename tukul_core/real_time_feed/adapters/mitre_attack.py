"""Adaptador para MITRE ATT&CK vía STIX/TAXII.

Proporciona tácticas, técnicas y procedimientos (TTPs) del framework
MITRE ATT&CK Enterprise. Se usa para enriquecer el contexto de amenazas
con el lenguaje común de la industria.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from tukul_core.http_safety import NO_REDIRECT_OPENER
from tukul_core.models import FeedEntry

from .base import SourceAdapter

ATTACK_ENTERPRISE_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/"
    "enterprise-attack/enterprise-attack.json"
)
HTTP_TIMEOUT = 30
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_MAX = 4.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
USER_AGENT = (
    "Tukul/ThreatFeed (+https://github.com/; "
    "contacto: mantenedor del repositorio)"
)


class MitreAttackAdapter(SourceAdapter):
    """Obtiene técnicas MITRE ATT&CK desde el repositorio CTI."""

    _cache: list[dict] | None = None
    _cache_ts: datetime | None = None
    _CACHE_TTL_MINUTES = 60

    @classmethod
    def source_id(cls) -> str:
        return "mitre-attack"

    @classmethod
    def label(cls) -> str:
        return "MITRE ATT&CK Enterprise"

    def fetch(self, hours: int) -> list[dict]:
        """Obtiene técnicas ATT&CK, con cache interno de 1 hora."""
        now = datetime.now(UTC)
        if self._cache is not None and self._cache_ts is not None:
            delta = now - self._cache_ts
            if delta < timedelta(minutes=self._CACHE_TTL_MINUTES):
                return self._cache

        request = urllib.request.Request(
            ATTACK_ENTERPRISE_URL, headers={"User-Agent": USER_AGENT}
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                data = json.loads(self._read_bounded(response))
                objects = data.get("objects", [])
                self._cache = objects
                self._cache_ts = now
                break
            except urllib.error.HTTPError as error:
                if error.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    self._sleep(error, attempt)
                    continue
                raise RuntimeError(
                    f"MITRE ATT&CK respondió {error.code}: {error.reason}"
                ) from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con MITRE ATT&CK: {error.reason}"
                ) from error
            except (TimeoutError, OSError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(None, attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con MITRE ATT&CK: {error}"
                ) from error
        else:
            raise RuntimeError(
                "No se pudo obtener MITRE ATT&CK tras los reintentos."
            )

        since = now - timedelta(hours=hours)
        techniques = [
            obj for obj in self._cache
            if obj.get("type") == "attack-pattern"
            and _parse_stix_date(obj.get("modified", ""), now) >= since
        ]
        return techniques

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte técnicas ATT&CK en FeedEntry."""
        entries: list[FeedEntry] = []
        for tech in raw:
            tech_id = tech.get("id", "")
            name = tech.get("name", "")
            if not tech_id or not name:
                continue

            description = tech.get("description", "")
            ext_refs = tech.get("external_references", [])
            url = next(
                (
                    r["url"] for r in ext_refs
                    if r.get("source_name") == "mitre-attack"
                ),
                f"https://attack.mitre.org/techniques/{tech_id}/",
            )

            modified = _parse_stix_date(
                tech.get("modified", ""), datetime.now(UTC)
            )

            entries.append(FeedEntry(
                source_id=f"mitre-attack:{tech_id}",
                source="mitre-attack",
                title=name,
                description=description[:500],
                url=url,
                published=modified,
                severity=None,
                confidence=0.9,
                topics=("ciberseguridad", "ttp", "mitre-attack"),
                tags=frozenset({"mitre-attack", "ttp", "attack-pattern"}),
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
                raise RuntimeError(
                    "La respuesta de MITRE ATT&CK supera el límite de bytes."
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _sleep(
        self, error: urllib.error.HTTPError | None, attempt: int
    ) -> None:
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


def _parse_stix_date(raw: str, default: datetime) -> datetime:
    """Parsea fecha STIX (ISO 8601)."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return default
