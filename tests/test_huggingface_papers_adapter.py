"""Pruebas del adaptador HuggingFace Papers (Task 2)."""

from tukul_core.real_time_feed.adapters.huggingface_papers import (
    HuggingFacePapersAdapter,
)

EJEMPLO = [
    {
        "paper": {
            "id": "2611.17190",
            "title": "Un paper de prueba",
            "summary": "Resumen del paper.",
            "publishedAt": "2026-11-13T00:00:00.000Z",
        },
        "publishedAt": "2026-11-13T00:00:00.000Z",
    }
]


def test_normalize_produce_entradas_con_url_https():
    adapter = HuggingFacePapersAdapter()
    entradas = adapter.normalize(EJEMPLO)
    assert len(entradas) == 1
    assert entradas[0].title == "Un paper de prueba"
    assert entradas[0].url.startswith("https://huggingface.co/papers/")
    assert "2611.17190" in entradas[0].url


def test_normalize_con_datos_invalidos_devuelve_vacio():
    adapter = HuggingFacePapersAdapter()
    assert adapter.normalize([{"paper": {}}, {}, "no-es-dict"]) == []


def test_source_id_y_label():
    assert HuggingFacePapersAdapter.source_id() == "huggingface-papers"
    assert HuggingFacePapersAdapter.label() == "HuggingFace Papers"
