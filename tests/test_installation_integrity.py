"""Guardas de integridad de la instalación.

Una herramienta debe arrancar y testearse sin pasos manuales. Estos tests
existen porque el repositorio llegó a un estado en el que el quality gate podía
pasar mientras el paquete, instalado de verdad, no importaba:

- `conftest.py` añadía la raíz a `sys.path`, así que pytest resolvía imports que
  un usuario real no resolvería.
- `pyproject.toml` declaraba una lista literal de paquetes que se quedó corta al
  añadir `tukul_core.real_time_feed`: la rueda se instalaba sin ese subpaquete y
  el comando instalado fallaba con `ModuleNotFoundError`.

Los tests aquí verifican propiedades del propio repositorio, no del código.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Módulo de primer nivel del producto. Todo lo que cuelgue de aquí debe entrar
# en la distribución: los subpaquetes se descubren con `find`, no con una lista
# manual que se desincroniza.
TOP_PACKAGE = "tukul_core"
PACKAGES = (TOP_PACKAGE, "tukul_ui")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _subpackages(root: Path) -> set[str]:
    """Subpaquetes reales bajo `root` (en formato con puntos, p. ej. a.b).

    Recorre solo directorios de Python: `rglob` sobre la raíz arrastraría
    `.venv` y `build`, que no forman parte de la distribución.
    """
    encontrados: set[str] = set()
    for init in root.rglob("__init__.py"):
        partes = init.relative_to(ROOT).parts
        if any(parte.startswith(".") or parte == "build" for parte in partes):
            continue
        encontrados.add(".".join(partes[:-1]))
    return encontrados


def test_packages_are_discovered_not_hardcoded():
    """La distribución descubre paquetes por patrón, no por lista literal.

    Una lista literal exige actualizarla en cada subpaquete nuevo; olvidarlo
    produce una rueda incompleta que solo falla en una instalación limpia
    (`tukul_core.real_time_feed` faltó y el comando instalado no arrancaba).
    """
    config = _pyproject()["tool"]["setuptools"]
    paquetes = config.get("packages")
    assert not isinstance(paquetes, list), "No vuelvas a fijar una lista literal de paquetes"
    assert isinstance(paquetes, dict) and "find" in paquetes, \
        "Falta [tool.setuptools.packages.find]"


def test_glob_include_covers_every_subpackage():
    """El patrón de `find` incluye todos los subpaquetes que existen en disco."""
    find = _pyproject()["tool"]["setuptools"]["packages"]["find"]
    include = find["include"]
    # `where` restringe el escaneo a la raíz del repo; sin él setuptools busca
    # también en .venv y build/, que no forman parte de la distribución.
    where = Path(find.get("where", ["."])[0]).resolve()
    assert where == ROOT.resolve(), f"where apunta fuera del repo: {where}"
    existentes = _subpackages(ROOT)
    fuera = [
        paquete for paquete in sorted(existentes)
        if not any(
            paquete == patron.rstrip("*") or paquete.startswith(patron.rstrip("*"))
            for patron in include
        )
    ]
    assert not fuera, f"Subpaquetes fuera de la distribución: {fuera}"
    assert f"{TOP_PACKAGE}.real_time_feed" in existentes


def test_realtime_feed_subpackage_is_importable():
    """El subpaquete que rompió la rueda importa (regresión concreta)."""
    modulo = importlib.import_module(f"{TOP_PACKAGE}.real_time_feed")
    assert Path(modulo.__file__).is_file()


def test_internal_imports_resolve_without_conftest():
    """Los paquetes se importan por sí solos, sin la ayuda de conftest.py.

    Se ejecuta en un subproceso desde un directorio ajeno al repo y con
    `PYTHONPATH` limpio; si el import solo funciona por el conftest o por el cwd,
    este test falla.
    """
    script = "import " + ", ".join(PACKAGES) + "; print('ok')"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"import falló fuera del repo:\n{result.stderr}"


def test_entry_point_module_is_declared():
    """El módulo de la CLI (`tukul`) se publica junto con los paquetes."""
    py_modules = _pyproject()["tool"]["setuptools"]["py-modules"]
    assert "tukul" in py_modules
    assert (ROOT / "tukul.py").is_file()
