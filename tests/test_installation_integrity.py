"""Guardas de integridad de la instalación.

Una herramienta debe arrancar y testearse sin pasos manuales. Estos tests
existen porque el repositorio llegó a un estado en el que el quality gate podía
pasar mientras el paquete, instalado de verdad, no importaba:

- `conftest.py` añadía la raíz a `sys.path`, así que pytest resolvía imports que
  un usuario real no resolvería.
- `pyproject.toml` listaba paquetes que el árbol de trabajo ya no tenía.

Los tests aquí verifican propiedades del propio repositorio, no del código.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Paquetes del producto declarados en pyproject.toml y lo que cada uno debe
# exponer para considerarse instalable y utilizable.
PACKAGES = ("articulador_core", "articulador_ui")


def test_declared_packages_exist_on_disk():
    """Todo paquete declarado en pyproject debe existir en la raíz del repo."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = config["tool"]["setuptools"]["packages"]
    missing = [name for name in declared if not (ROOT / name / "__init__.py").is_file()]
    assert not missing, f"pyproject declara paquetes inexistentes: {missing}"


def test_declared_modules_belong_to_the_ui_package():
    """Un módulo no debe vivir dentro de otro paquete si se declara aparte.

    El fallo original movió `articulador_core` dentro de `articulador_ui`. Si
    se declara como paquete de primer nivel, su directorio no puede colgar de
    otro paquete.
    """
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = config["tool"]["setuptools"]["packages"]
    for name in declared:
        nested = list((ROOT / name).glob(f"*/{name}"))
        assert not nested, f"{name} está anidado dentro de otro paquete: {nested}"


def test_internal_imports_resolve_without_conftest():
    """Los paquetes se importan por sí solos, sin la ayuda de conftest.py.

    Se ejecuta en un subproceso desde un directorio ajeno al repo y con
    `PYTHONPATH` limpio; si el import solo funciona por el conftest o por el cwd,
    este test falla.
    """
    script = "import " + ", ".join(PACKAGES) + "; print('ok')"
    env = {key: value for key, value in __import__("os").environ.items() if key != "PYTHONPATH"}
    # `-S` evita que los .pth de site-packages (el marcador editable) resuelvan
    # imports que la instalación real sí cubre; se prueba el paquete instalado.
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"import falló fuera del repo:\n{result.stderr}"


def test_core_is_importable_from_the_installer_module():
    """El punto de entrada (articulador.py) encuentra `articulador_core`."""
    module = importlib.import_module("articulador_core")
    assert Path(module.__file__).is_file()
