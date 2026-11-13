"""Pruebas del autoindexado de la memoria al arrancar (Task 5)."""

from pathlib import Path

from tukul_core.memory.index import CorpusIndex
from tukul_core.memory.policy import MemoryPolicy
from tukul_core.memory.repository import FileMemoryRepository


def test_el_autoindexado_puebla_el_indice(tmp_path):
    """El contrato que usa `_autoindexar_memoria` puebla el índice y busca."""
    root = tmp_path / "Articulos"
    root.mkdir()
    (root / "uno.md").write_text("# Tema uno\ncontenido singular", encoding="utf-8")
    db = tmp_path / "memory.sqlite3"

    repo = FileMemoryRepository(MemoryPolicy(root=root, max_file_bytes=50_000))
    with CorpusIndex(db) as index:
        stats = index.refresh(repo)
        assert stats.indexed == 1
        assert stats.scanned == 1
        assert index.search("singular")


def test_el_refresco_es_incremental(tmp_path):
    """Un segundo refresco sin cambios no reindexa nada."""
    root = tmp_path / "Articulos"
    root.mkdir()
    (root / "uno.md").write_text("# Tema\ncontenido", encoding="utf-8")
    db = tmp_path / "memory.sqlite3"
    repo = FileMemoryRepository(MemoryPolicy(root=root, max_file_bytes=50_000))

    with CorpusIndex(db) as index:
        index.refresh(repo)
        stats2 = index.refresh(repo)
        assert stats2.indexed == 0
        assert stats2.unchanged == 1
