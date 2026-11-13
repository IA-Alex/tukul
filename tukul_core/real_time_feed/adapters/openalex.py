"""Adaptador para OpenAlex (trabajos académicos).

Consulta la API pública de OpenAlex filtrada por el concepto de inteligencia
artificial, ordenada por fecha de publicación descendente. No requiere API key;
OpenAlex agradece identificación del cliente (correo) para el «polite pool».
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from tukul_core.http_safety import NO_REDIRECT_OPENER
from tukul_core.models import FeedEntry

from .._dates import parse_feed_date
from .base import SourceAdapter

OPENALEX_URL = "https://api.openalex.org/works"
# Concepto «Artificial intelligence» de OpenAlex.
OPENALEX_AI_CONCEPT = "C154945302"
HTTP_TIMEOUT = 30
MAX_ATTEMPTS = 2
BACKOFF_BASE = 0.5
BACKOFF_MAX = 2.0
# La respuesta de 25 works con abstracts reconstruidos ronda el megabyte; 8 MB
# deja margen sin dejar de acotar una respuesta anómala.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
USER_AGENT = "Tukul/ThreatFeed (mailto:mantenedor@example.invalid)"


class OpenAlexAdapter(SourceAdapter):
    """Obtiene trabajos recientes de inteligencia artificial desde OpenAlex."""

    @classmethod
    def source_id(cls) -> str:
        return "openalex"

    @classmethod
    def label(cls) -> str:
        return "OpenAlex"

    def fetch(self, hours: int, **kwargs: Any) -> list[dict]:
        """Obtiene los works recientes del concepto de IA."""
        params = urllib.parse.urlencode({
            "filter": f"concepts.id:{OPENALEX_AI_CONCEPT}",
            "sort": "publication_date:desc",
            "per-page": 25,
        })
        url = f"{OPENALEX_URL}?{params}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                body = self._read_bounded(response)
                datos = json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"OpenAlex respondió {error.code}: {error.reason}"
                ) from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con OpenAlex: {error.reason}"
                ) from error
            except (TimeoutError, OSError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con OpenAlex: {error}"
                ) from error
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Cuerpo no JSON: la fuente cambió o respondió un error en HTML.
                return []
            resultados = datos.get("results") if isinstance(datos, dict) else None
            return resultados if isinstance(resultados, list) else []
        return []

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte los works crudos en FeedEntry, sin lanzar nunca."""
        entries: list[FeedEntry] = []
        vistos: set[str] = set()
        for work in raw:
            if not isinstance(work, dict):
                continue
            work_id = work.get("id")
            title = work.get("title")
            if not isinstance(work_id, str) or not work_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            if work_id in vistos:
                continue
            vistos.add(work_id)
            # `landing_page_url` es el enlace del editor; si falta (muchos works
            # no lo traen), se usa la URL canónica de OpenAlex, que siempre
            # existe y es https.
            primary = work.get("primary_location")
            landing = primary.get("landing_page_url") if isinstance(primary, dict) else None
            url = landing if isinstance(landing, str) and landing.startswith("https://") else work_id
            fecha = work.get("publication_date") or ""
            entries.append(FeedEntry(
                source_id=f"openalex:{work_id}",
                source="openalex",
                title=title.strip()[:200],
                description="",
                url=url,
                published=parse_feed_date(fecha, default=datetime.now(UTC)),
                severity=None,
                confidence=0.8,
                topics=("investigacion", "inteligencia_artificial"),
                tags=frozenset({"openalex", "inteligencia_artificial"}),
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
                raise RuntimeError("OpenAlex respuesta supera límite.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _sleep(self, attempt: int) -> None:
        """Backoff exponencial con jitter (0-25 % aleatorio)."""
        delay = BACKOFF_BASE * (2 ** (attempt - 1))
        jitter = delay * 0.25 * random.random()  # nosec B311 - jitter de backoff, no criptográfico
        delay = min(delay + jitter, BACKOFF_MAX * 1.25)
        time.sleep(delay)
