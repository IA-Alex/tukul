"""Proveedores de descubrimiento web.

El proveedor devuelve metadatos, no descarga artículos. Esto mantiene separadas
la búsqueda amplia y la verificación posterior de una fuente primaria.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from tukul_core.http_safety import NO_REDIRECT_OPENER

from .models import SearchQuery, SearchResult

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HTTP_TIMEOUT = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
USER_AGENT = "Tukul/0.1 (búsqueda bajo demanda; no descarga artículos)"


class SearchProvider(ABC):
    """Contrato para añadir buscadores sin acoplar la interfaz a uno solo."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Identificador estable del proveedor."""
        ...

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Busca señales y devuelve solo metadatos trazables."""
        ...


class GdeltProvider(SearchProvider):
    """Descubrimiento global sin API key, usando GDELT DOC 2.0."""

    @property
    def provider_id(self) -> str:
        return "gdelt"

    def search(self, query: SearchQuery) -> list[SearchResult]:
        params = urllib.parse.urlencode({
            "query": query.text,
            "mode": "artlist",
            "format": "json",
            "maxrecords": query.max_results,
            "timespan": f"{query.days}d",
            "sort": "datedesc",
        })
        request = urllib.request.Request(
            f"{GDELT_URL}?{params}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
            body = self._read_bounded(response)
            payload = json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"GDELT respondió {error.code}.") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"No se pudo consultar GDELT: {error}") from error
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise RuntimeError("GDELT devolvió una respuesta inválida.") from error

        if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
            return []
        return [result for item in payload["articles"] if (result := self._normalize(item))]

    def _normalize(self, item: Any) -> SearchResult | None:
        if not isinstance(item, dict):
            return None
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        if not url.startswith("https://") or not title:
            return None
        parsed = urllib.parse.urlsplit(url)
        published = self._parse_date(item.get("seendate"))
        return SearchResult(
            result_id=url,
            provider=self.provider_id,
            title=title[:300],
            snippet=str(item.get("snippet", "")).strip()[:1000],
            url=url,
            domain=parsed.hostname or "",
            published=published,
            language=str(item.get("language", "")).strip() or None,
            metadata={
                key: str(item[key])
                for key in ("domain", "sourcecountry", "sourcecollection")
                if item.get(key) is not None
            },
        )

    @staticmethod
    def _parse_date(value: Any) -> datetime | None:
        if not isinstance(value, str) or len(value) < 14:
            return None
        try:
            return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _read_bounded(response: Any) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("La respuesta del buscador supera el límite permitido.")
            chunks.append(chunk)
        return b"".join(chunks)
