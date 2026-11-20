"""Identidad de build para soporte y diagnóstico."""

from types import SimpleNamespace

from tukul_core import version


def test_build_commit_marca_arbol_sucio(monkeypatch, tmp_path):
    monkeypatch.delenv("TUKUL_COMMIT", raising=False)
    resultados = iter(
        [
            SimpleNamespace(returncode=0, stdout="abc123\n"),
            SimpleNamespace(returncode=0, stdout=" M archivo.py\n"),
        ]
    )
    monkeypatch.setattr(version.subprocess, "run", lambda *args, **kwargs: next(resultados))

    assert version.build_commit(tmp_path) == "abc123-dirty"


def test_build_commit_mantiene_hash_en_arbol_limpio(monkeypatch, tmp_path):
    monkeypatch.delenv("TUKUL_COMMIT", raising=False)
    resultados = iter(
        [
            SimpleNamespace(returncode=0, stdout="abc123\n"),
            SimpleNamespace(returncode=0, stdout=""),
        ]
    )
    monkeypatch.setattr(version.subprocess, "run", lambda *args, **kwargs: next(resultados))

    assert version.build_commit(tmp_path) == "abc123"
