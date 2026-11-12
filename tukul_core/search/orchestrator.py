"""Orquestación de búsquedas explícitas y deduplicadas."""

from __future__ import annotations

from collections.abc import Iterable

from .models import SearchQuery, SearchResult
from .providers import GdeltProvider, SearchProvider


class SearchOrchestrator:
    """Consulta proveedores de descubrimiento sin ingerir contenido completo."""

    def __init__(self, providers: Iterable[SearchProvider] | None = None) -> None:
        self.providers = list(providers or (GdeltProvider(),))

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Devuelve resultados únicos; un proveedor caído no oculta los demás."""
        results: list[SearchResult] = []
        seen: set[str] = set()
        errors: list[str] = []
        for provider in self.providers:
            try:
                found = provider.search(query)
            except RuntimeError as error:
                errors.append(f"{provider.provider_id}: {error}")
                continue
            for result in found:
                key = result.url.rstrip("/").lower()
                if key not in seen:
                    seen.add(key)
                    results.append(result)
        if not results and errors:
            raise RuntimeError("Ningún proveedor de búsqueda respondió. " + "; ".join(errors))
        return results[:query.max_results]
