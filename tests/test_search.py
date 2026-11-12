"""Pruebas de búsqueda bajo demanda sin consumir servicios externos."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tukul_core.search import GdeltProvider, SearchOrchestrator, SearchQuery
from tukul_core.search import providers as providers_module


def test_query_rechaza_texto_vacio_y_limites_invalidos():
    with pytest.raises(ValueError):
        SearchQuery(" ")
    with pytest.raises(ValueError):
        SearchQuery("tema", days=0)
    with pytest.raises(ValueError):
        SearchQuery("tema", max_results=101)


def test_gdelt_normaliza_solo_resultados_https(monkeypatch):
    payload = {
        "articles": [
            {
                "url": "https://example.org/alerta",
                "title": "Alerta técnica",
                "snippet": "Resumen breve",
                "seendate": "20261111153000",
                "language": "Spanish",
                "domain": "example.org",
                "sourcecountry": "MX",
            },
            {"url": "http://inseguro.example/descartar", "title": "No usar"},
        ]
    }

    class Response:
        def __init__(self):
            self._body = json.dumps(payload).encode()

        def read(self, _size):
            body, self._body = self._body, b""
            return body

    monkeypatch.setattr(
        providers_module.NO_REDIRECT_OPENER,
        "open",
        lambda request, timeout: Response(),
    )
    results = GdeltProvider().search(SearchQuery("vulnerabilidad", max_results=5))

    assert len(results) == 1
    assert results[0].url == "https://example.org/alerta"
    assert results[0].published == datetime(2026, 11, 11, 15, 30, tzinfo=UTC)


def test_orquestador_deduplica_urls_y_degrada_por_proveedor():
    class Bueno:
        provider_id = "bueno"

        def search(self, _query):
            from tukul_core.search.models import SearchResult

            return [SearchResult("a", "bueno", "A", "", "https://x.test/a", "x.test")]

    class Roto:
        provider_id = "roto"

        def search(self, _query):
            raise RuntimeError("caído")

    results = SearchOrchestrator([Bueno(), Roto()]).search(SearchQuery("tema"))
    assert [result.url for result in results] == ["https://x.test/a"]


def test_orquestador_informa_si_todos_los_proveedores_fallan():
    class Roto:
        provider_id = "roto"

        def search(self, _query):
            raise RuntimeError("caído")

    with pytest.raises(RuntimeError, match="Ningún proveedor"):
        SearchOrchestrator([Roto()]).search(SearchQuery("tema"))
