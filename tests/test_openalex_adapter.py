"""Pruebas del adaptador OpenAlex (Task 3)."""

from tukul_core.real_time_feed.adapters.openalex import OpenAlexAdapter

EJEMPLO = [
    {
        "id": "https://openalex.org/W123",
        "title": "Un trabajo de prueba",
        "publication_date": "2026-11-13",
        "primary_location": {"landing_page_url": "https://ejemplo.org/w123"},
    }
]


def test_normalize_produce_entradas():
    adapter = OpenAlexAdapter()
    entradas = adapter.normalize(EJEMPLO)
    assert len(entradas) == 1
    assert entradas[0].title == "Un trabajo de prueba"
    assert entradas[0].url == "https://ejemplo.org/w123"


def test_normalize_sin_landing_page_cae_al_id_openalex():
    adapter = OpenAlexAdapter()
    entradas = adapter.normalize([{
        "id": "https://openalex.org/W9",
        "title": "Sin landing",
        "publication_date": "2026-11-13",
        "primary_location": {},
    }])
    assert entradas[0].url == "https://openalex.org/W9"


def test_normalize_con_datos_invalidos_devuelve_vacio():
    assert OpenAlexAdapter().normalize([{}, {"title": ""}, "x"]) == []


def test_source_id_y_label():
    assert OpenAlexAdapter.source_id() == "openalex"
    assert OpenAlexAdapter.label() == "OpenAlex"
