"""Pruebas de búsqueda bajo demanda sin consumir servicios externos."""

from __future__ import annotations

import json
import urllib.parse
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


def test_gdelt_inyecta_sourcelang_cuando_se_pide_idioma(monkeypatch):
    """H-02: `SearchQuery.language` debe llegar a GDELT como `sourcelang:`."""
    capturado: dict[str, str] = {}

    class Response:
        def __init__(self):
            self._body = json.dumps({"articles": []}).encode()

        def read(self, _size):
            body, self._body = self._body, b""
            return body

    def open_(request, timeout):
        capturado["url"] = request.full_url
        return Response()

    monkeypatch.setattr(providers_module.NO_REDIRECT_OPENER, "open", open_)
    GdeltProvider().search(SearchQuery("vulnerabilidad", language="spanish"))

    query_decodificada = urllib.parse.unquote(capturado["url"])
    assert "sourcelang:spanish" in query_decodificada


def test_gdelt_sin_idioma_no_anade_sourcelang(monkeypatch):
    capturado: dict[str, str] = {}

    class Response:
        def __init__(self):
            self._body = json.dumps({"articles": []}).encode()

        def read(self, _size):
            body, self._body = self._body, b""
            return body

    def open_(request, timeout):
        capturado["url"] = request.full_url
        return Response()

    monkeypatch.setattr(providers_module.NO_REDIRECT_OPENER, "open", open_)
    GdeltProvider().search(SearchQuery("vulnerabilidad"))

    assert "sourcelang" not in capturado["url"]


def test_gdelt_reintenta_tras_429_y_devuelve_resultados(monkeypatch):
    """H-01: un 429 transitorio debe reintentarse, no fallar de inmediato."""
    import urllib.error

    intentos = {"n": 0}

    class Response:
        def __init__(self):
            self._body = json.dumps({"articles": [
                {"url": "https://example.org/a", "title": "T", "seendate": "20261111153000"},
            ]}).encode()

        def read(self, _size):
            body, self._body = self._body, b""
            return body

    def open_(request, timeout):
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "slow down", {"Retry-After": "0"}, None)
        return Response()

    monkeypatch.setattr(providers_module.NO_REDIRECT_OPENER, "open", open_)
    monkeypatch.setattr(providers_module.time, "sleep", lambda _s: None)
    results = GdeltProvider().search(SearchQuery("tema"))

    assert intentos["n"] == 2
    assert len(results) == 1


def test_gdelt_429_persistente_agota_intentos_y_lanza(monkeypatch):
    import urllib.error

    intentos = {"n": 0}

    def open_(request, timeout):
        intentos["n"] += 1
        raise urllib.error.HTTPError(request.full_url, 429, "slow down", {}, None)

    monkeypatch.setattr(providers_module.NO_REDIRECT_OPENER, "open", open_)
    monkeypatch.setattr(providers_module.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="429"):
        GdeltProvider().search(SearchQuery("tema"))

    assert intentos["n"] == providers_module.MAX_ATTEMPTS


def test_gdelt_error_no_reintentable_falla_de_inmediato(monkeypatch):
    import urllib.error

    intentos = {"n": 0}

    def open_(request, timeout):
        intentos["n"] += 1
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(providers_module.NO_REDIRECT_OPENER, "open", open_)
    monkeypatch.setattr(providers_module.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="404"):
        GdeltProvider().search(SearchQuery("tema"))

    assert intentos["n"] == 1
