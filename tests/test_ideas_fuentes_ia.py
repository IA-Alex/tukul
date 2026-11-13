"""Pruebas de integración de las fuentes de IA en el flujo de Ideas (Task 4)."""

from tukul_core.real_time_feed.adapters import REGISTRY


def test_las_fuentes_de_ia_estan_registradas():
    """HuggingFace Papers y OpenAlex participan del pipeline por el REGISTRY."""
    assert "huggingface-papers" in REGISTRY
    assert "openalex" in REGISTRY


def test_las_fuentes_de_amenaza_siguen_registradas():
    """No se retiró ninguna fuente existente al añadir las de IA."""
    for fuente in ("nvd", "epss", "kev", "mitre-attack", "arxiv"):
        assert fuente in REGISTRY


def test_el_texto_de_confirmacion_menciona_las_fuentes_de_ia():
    """La confirmación del diálogo informa las fuentes que se consultarán."""
    from pathlib import Path

    codigo = Path("tukul_ui/ideas.py").read_text(encoding="utf-8")
    assert "HuggingFace Papers" in codigo
    assert "OpenAlex" in codigo
