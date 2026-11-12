from pathlib import Path
from unittest.mock import patch

from tukul_core.memory import CorpusIndex, FileMemoryRepository, MemoryPolicy


def _repository(root: Path) -> FileMemoryRepository:
    return FileMemoryRepository(
        MemoryPolicy(root=root, excluded_directories=frozenset({"plugins"}))
    )


def test_repository_includes_text_and_excludes_sensitive_or_binary_files(tmp_path):
    (tmp_path / "tema.md").write_text("# Sicofancia\nLa IA puede complacer.", encoding="utf-8")
    (tmp_path / "nota.txt").write_text("Contexto editorial", encoding="utf-8")
    (tmp_path / "mi_perfil.txt").write_text("dato privado", encoding="utf-8")
    (tmp_path / "imagen.png").write_bytes(b"\x89PNG\x00binary")
    (tmp_path / "binario.md").write_bytes(b"texto\x00binario")
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "skill.md").write_text("no indexar", encoding="utf-8")

    documents = list(_repository(tmp_path).iter_documents())

    assert [document.relative_path for document in documents] == ["nota.txt", "tema.md"]
    assert documents[1].title == "Sicofancia"
    assert documents[1].category == "article"


def test_policy_normalizes_extensions_and_blocks_private_or_backup_paths(tmp_path):
    policy = MemoryPolicy(
        root=tmp_path,
        include_extensions=frozenset({"MD"}),
        private_prefixes=("privado",),
    ).normalized()

    assert policy.include_extensions == frozenset({".md"})
    assert policy.allows("publicado.md", 10)
    assert not policy.allows("privado/nota.md", 10)
    assert not policy.allows("copia.md~", 10)
    assert not policy.allows("nota.md", 50_001)
    assert not policy.allows("nota.pdf", 10)


def test_repository_handles_missing_root_limits_and_unreadable_text(tmp_path):
    assert list(_repository(tmp_path / "missing").iter_documents()) == []
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe")
    (tmp_path / "stat-error.md").write_text("ignored", encoding="utf-8")
    limited = FileMemoryRepository(MemoryPolicy(root=tmp_path, max_files=1))
    assert len(list(limited.iter_documents())) == 1

    real_stat = Path.stat

    def failing_stat(path, *args, **kwargs):
        if path.name == "stat-error.md":
            raise OSError("stat failure")
        return real_stat(path, *args, **kwargs)

    with patch.object(Path, "stat", failing_stat):
        documents = list(_repository(tmp_path).iter_documents())
    assert all(document.relative_path != "stat-error.md" for document in documents)


def test_repository_classifies_extensionless_text(tmp_path):
    (tmp_path / "nota").write_text("contenido", encoding="utf-8")
    document = next(iter(_repository(tmp_path).iter_documents()))
    assert document.category == "text"


def test_repository_reads_only_safe_indexed_paths(tmp_path):
    article = tmp_path / "tema.md"
    article.write_text("# Tema\nContenido", encoding="utf-8")
    repository = _repository(tmp_path)

    document = repository.read_document("tema.md")

    assert document is not None
    assert document.content == "# Tema\nContenido"
    assert repository.read_document("../tema.md") is None
    assert repository.read_document("no-existe.md") is None


def test_index_refreshes_incrementally_and_removes_deleted_documents(tmp_path):
    article = tmp_path / "tema.md"
    article.write_text("# Sicofancia\nCriterio humano", encoding="utf-8")
    database = tmp_path / "state" / "memory.sqlite3"

    with CorpusIndex(database) as index:
        first = index.refresh(_repository(tmp_path))
        second = index.refresh(_repository(tmp_path))
        assert (first.indexed, first.unchanged, first.removed) == (1, 0, 0)
        assert (second.indexed, second.unchanged, second.removed) == (0, 1, 0)
        assert index.search("criterio")[0].relative_path == "tema.md"

        article.unlink()
        third = index.refresh(_repository(tmp_path))
        assert third.removed == 1
        assert index.search("criterio") == []


def test_search_ignores_fts_operators_and_returns_traceable_excerpt(tmp_path):
    (tmp_path / "seguridad.md").write_text(
        "# Seguridad\nLa evaluación de modelos requiere criterio y evidencia.",
        encoding="utf-8",
    )
    with CorpusIndex(tmp_path / "memory.sqlite3") as index:
        index.refresh(_repository(tmp_path))
        results = index.search('criterio OR "evidencia"')

    assert len(results) == 1
    assert results[0].relative_path == "seguridad.md"
    assert "criterio" in results[0].excerpt.lower()


def test_el_recorte_no_se_desalinea_con_texto_que_casefold_expande(tmp_path):
    """El fragmento debe contener el término aunque casefold cambie la longitud.

    Defecto observado: `_excerpt` buscaba la posición sobre `content.casefold()`
    y rebanaba el contenido original. `casefold` puede alargar la cadena («ß»→
    «ss», «İ»→«i̇»), así que la ventana se corría y podía quedar vacía, omitiendo
    el término buscado en el fragmento mostrado al usuario.
    """
    (tmp_path / "ruido.md").write_text(
        "ß" * 500 + " alpha",  # 506 chars; casefold alarga a ~1007
        encoding="utf-8",
    )
    with CorpusIndex(tmp_path / "memory.sqlite3") as index:
        index.refresh(_repository(tmp_path))
        results = index.search("alpha")

    assert len(results) == 1
    assert "alpha" in results[0].excerpt


def test_search_validates_limit(tmp_path):
    with CorpusIndex(tmp_path / "memory.sqlite3") as index:
        try:
            index.search("tema", limit=0)
        except ValueError as error:
            assert "limit" in str(error)
        else:
            raise AssertionError("Se esperaba validar el límite")


def test_search_returns_empty_for_non_text_query(tmp_path):
    with CorpusIndex(tmp_path / "memory.sqlite3") as index:
        assert index.search("!!!") == []
