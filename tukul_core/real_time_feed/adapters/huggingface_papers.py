"""Adaptador para HuggingFace Papers (papers destacados del día).

Consulta el endpoint público de papers diarios de HuggingFace, que no requiere
API key. Devuelve los papers como entradas normalizadas de inteligencia
artificial, para el flujo de ideas de artículo.
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

from .._dates import parse_feed_date
from .base import SourceAdapter

# https y sin redirects, igual que el resto de adaptadores: el opener propio
# rechaza redirecciones para no reenviar credenciales ni aceptar cuerpos de
# otro origen.
HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HTTP_TIMEOUT = 30
MAX_ATTEMPTS = 2
BACKOFF_BASE = 0.5
BACKOFF_MAX = 2.0
# El listado diario es pequeño (unos pocos cientos de KB); 4 MB deja margen sin
# dejar de acotar una respuesta anómala.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
USER_AGENT = (
    "Tukul/ThreatFeed (+https://github.com/; "
    "contacto: mantenedor del repositorio)"
)


class HuggingFacePapersAdapter(SourceAdapter):
    """Obtiene los papers diarios destacados de HuggingFace."""

    @classmethod
    def source_id(cls) -> str:
        return "huggingface-papers"

    @classmethod
    def label(cls) -> str:
        return "HuggingFace Papers"

    def fetch(self, hours: int, **kwargs: Any) -> list[dict]:
        """Obtiene el JSON de papers diarios (sin filtrar por `hours`)."""
        request = urllib.request.Request(
            HF_PAPERS_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                body = self._read_bounded(response)
                datos = json.loads(body.decode("utf-8"))
                return datos if isinstance(datos, list) else []
            except urllib.error.HTTPError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"HuggingFace Papers respondió {error.code}: {error.reason}"
                ) from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con HuggingFace Papers: {error.reason}"
                ) from error
            except (TimeoutError, OSError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con HuggingFace Papers: {error}"
                ) from error
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Cuerpo no JSON: la fuente cambió o respondió con un error en
                # HTML. No hay nada que reintentar; se degrada a lista vacía.
                return []
        return []

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte los papers crudos en FeedEntry, sin lanzar nunca."""
        entries: list[FeedEntry] = []
        vistos: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            paper = item.get("paper")
            if not isinstance(paper, dict):
                continue
            paper_id = paper.get("id")
            title = paper.get("title")
            if not isinstance(paper_id, str) or not paper_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            if paper_id in vistos:
                continue
            vistos.add(paper_id)
            summary = paper.get("summary")
            if not isinstance(summary, str):
                summary = ""
            fecha = paper.get("publishedAt") or item.get("publishedAt") or ""
            entries.append(FeedEntry(
                source_id=f"huggingface-papers:{paper_id}",
                source="huggingface-papers",
                title=title.strip()[:200],
                description=summary.strip()[:500],
                url=f"https://huggingface.co/papers/{paper_id}",
                published=parse_feed_date(fecha, default=datetime.now(UTC)),
                severity=None,
                confidence=0.85,
                topics=("investigacion", "inteligencia_artificial", "paper"),
                tags=frozenset({"huggingface", "paper", "inteligencia_artificial"}),
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
                raise RuntimeError("HuggingFace Papers respuesta supera límite.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _sleep(self, attempt: int) -> None:
        """Backoff exponencial con jitter (0-25 % aleatorio)."""
        delay = BACKOFF_BASE * (2 ** (attempt - 1))
        jitter = delay * 0.25 * random.random()  # nosec B311 - jitter de backoff, no criptográfico
        delay = min(delay + jitter, BACKOFF_MAX * 1.25)
        time.sleep(delay)
