"""Equivalencia entre `uv.lock` y `requirements-dev.lock`.

Hallazgo de la auditoría 2026-11-04 (BAJO): los dos lockfiles del repo podían
declarar versiones distintas sin que nada lo detectara. `uv.lock` se quedó en
`tukul 0.3.2` y sin `pytest-timeout` ni `locust` tras añadirlos a
`pyproject.toml`, mientras `requirements-dev.lock` (compilado después) sí los
tenía: dos fuentes de verdad que se desincronizan en silencio.

La reparación no es fijar versiones a mano (eso desincroniza otra vez): es fijar
la **regla** de que ambos archivos coinciden, y que la próxima divergencia falle
aquí. `requirements-dev.lock` se genera con
`uv export --format requirements-txt --no-emit-project --extra dev --extra keyring`,
que lo deriva de `uv.lock` por construcción.
"""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UV_LOCK = RAIZ / "uv.lock"
REQ_LOCK = RAIZ / "requirements-dev.lock"

# Dependencias directas del proyecto (runtime + extras dev/keyring). No se
# comparan las transitivas: su resolución puede variar por marcadores de
# plataforma, y lo que importa es que las declaradas no divergan.
DIRECTAS = (
    "tomli-w", "keyring",
    "pytest", "pytest-cov", "pytest-timeout", "ruff", "mypy", "pip-audit",
    "bandit", "locust",
)


def _versiones_uv() -> dict[str, str]:
    """{nombre: versión} de todos los paquetes resueltos en `uv.lock`."""
    datos = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    return {p["name"].lower(): p.get("version", "") for p in datos.get("package", [])}


def _versiones_requirements() -> dict[str, str]:
    """{nombre: versión} de las líneas `paquete==versión` del lock compilado."""
    versiones: dict[str, str] = {}
    for linea in REQ_LOCK.read_text(encoding="utf-8").splitlines():
        coincidencia = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", linea)
        if coincidencia:
            versiones[coincidencia.group(1).lower()] = coincidencia.group(2)
    return versiones


class TestLockfilesEquivalentes(unittest.TestCase):
    def setUp(self) -> None:
        self.uv = _versiones_uv()
        self.req = _versiones_requirements()

    def test_las_dependencias_directas_coinciden(self):
        divergencias = []
        for paquete in DIRECTAS:
            en_uv = self.uv.get(paquete)
            en_req = self.req.get(paquete)
            if en_uv != en_req:
                divergencias.append(f"{paquete}: uv.lock={en_uv!r} requirements={en_req!r}")
        self.assertEqual(
            divergencias, [],
            "Los lockfiles declaran versiones distintas; regenera "
            "`requirements-dev.lock` con `uv export` desde `uv.lock`.\n"
            + "\n".join(divergencias),
        )

    def test_uv_lock_conoce_las_dependencias_declaradas(self):
        """Toda dependencia directa de `pyproject.toml` está en `uv.lock`.

        Es la comprobación que habría detectado el lock obsoleto: `uv.lock` se
        actualizó sin `pytest-timeout` ni `locust` al añadirlos al proyecto.
        """
        faltantes = [p for p in DIRECTAS if p not in self.uv]
        self.assertEqual(
            faltantes, [],
            f"uv.lock no conoce estas dependencias declaradas: {faltantes}. "
            "Ejecuta `uv lock`.",
        )

    def test_uv_lock_fija_la_version_del_proyecto(self):
        """`uv.lock` no puede quedarse con una versión antigua del proyecto."""
        pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
        version_proyecto = pyproject["project"]["version"]
        self.assertEqual(
            self.uv.get("tukul"), version_proyecto,
            "uv.lock fija una versión de tukul distinta de pyproject.toml; ejecuta `uv lock`.",
        )


if __name__ == "__main__":
    unittest.main()
