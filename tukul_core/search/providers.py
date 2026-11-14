"""Proveedores de descubrimiento web.

El proveedor devuelve metadatos, no descarga artículos. Esto mantiene separadas
la búsqueda amplia y la verificación posterior de una fuente primaria.
"""

from __future__ import annotations

import json
import random
import time
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

# GDELT limita el acceso sin key a ~1 petición cada 5 s por IP y responde 429
# cuando se excede. A diferencia de los adaptadores de feed, este proveedor no
# reintentaba: cualquier ráfaga o cuota compartida agotada devolvía error y cero
# resultados. Se acota con reintentos y un intervalo mínimo entre llamadas,
# mismo patrón que `nvd.py::_sleep` y `arxiv.py::_wait_for_rate_limit`.
GDELT_MIN_REQUEST_INTERVAL = 5.0
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 8.0


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

    def __init__(self) -> None:
        # Marca temporal de la última petición, para respetar el intervalo
        # mínimo entre llamadas del mismo proveedor.
        self._last_request_at = 0.0

    @property
    def provider_id(self) -> str:
        return "gdelt"

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Busca en GDELT DOC 2.0 con reintentos y respeto del rate-limit.

        GDELT responde 429 cuando se supera ~1 petición/5 s por IP. Se
        reintenta de forma acotada ante estados transitorios (respetando
        `Retry-After` si viene) y se espera el intervalo mínimo entre
        llamadas del mismo proceso.
        """
        params = urllib.parse.urlencode({
            "query": self._build_query(query),
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
            response = self._open_with_retry(request)
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

    @staticmethod
    def _build_query(query: SearchQuery) -> str:
        """Combina el texto con el filtro de idioma de GDELT si se pidió uno.

        GDELT filtra por idioma con el operador `sourcelang:` dentro de la
        query (no hay parámetro aparte). Se espera el nombre del idioma en
        inglés (`spanish`, `english`, …), que es lo que GDELT documenta.
        """
        if query.language:
            return f"{query.text} sourcelang:{query.language}"
        return query.text

    def _open_with_retry(self, request: urllib.request.Request) -> Any:
        """Abre la conexión reintentando solo errores transitorios.

        Antes, un 429 devolvía error de inmediato: cualquier ráfaga o cuota
        compartida agotada dejaba la búsqueda sin resultados. Se reintenta
        `MAX_ATTEMPTS` veces con backoff exponencial y jitter, respetando
        `Retry-After` cuando el proveedor lo envía. Los errores no
        reintentables se relanzan tal cual.
        """
        last_error: BaseException | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._wait_for_rate_limit()
                return NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                    raise
                self._sleep(error, attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = error
                if attempt == MAX_ATTEMPTS:
                    raise
                self._sleep(None, attempt)
        raise last_error  # type: ignore[misc]  # inalcanzable: el bucle siempre retorna o relanza

    def _wait_for_rate_limit(self) -> None:
        """Espera lo necesario para respetar el intervalo mínimo entre llamadas.

        GDELT pide ~1 petición cada 5 s por IP sin key. El estado es de
        instancia: una ráfaga dentro del mismo proveedor no dispara el 429.
        """
        ahora = time.monotonic()
        espera = GDELT_MIN_REQUEST_INTERVAL - (ahora - self._last_request_at)
        if espera > 0:
            time.sleep(espera)
        self._last_request_at = time.monotonic()

    def _sleep(self, error: urllib.error.HTTPError | None, attempt: int) -> None:
        """Backoff exponencial con jitter; respeta `Retry-After` si viene."""
        delay = min(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_MAX_SECONDS)
        if error is not None:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            if retry_after:
                try:
                    delay = min(max(float(retry_after), 0.0), BACKOFF_MAX_SECONDS)
                except (ValueError, TypeError):
                    pass
        delay += delay * 0.25 * random.random()
        time.sleep(delay)

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
