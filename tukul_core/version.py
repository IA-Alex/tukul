"""Identidad de la compilación: versión y commit, best-effort.

El diagnóstico `--health` no decía QUÉ versión se estaba ejecutando. Sin eso,
un reporte de soporte («a mí me falla») era irresoluble: no se podía distinguir
una instalación vieja de la última, ni correlacionar con un commit.

La versión sale de los metadatos del paquete (`pyproject.toml` → rueda); en un
ejecutable hecho con PyInstaller los metadatos pueden no estar, así que hay
respaldo declarado. El commit sale de `git` si el árbol es un repo y de la
variable `TUKUL_COMMIT` (que el pipeline de release puede inyectar), porque en
el binario no existe `.git`.
"""
from __future__ import annotations

import os
import subprocess
from importlib import metadata
from pathlib import Path

#: Valor devuelto cuando no se puede determinar la versión. No se inventa un
#: número: decir «desconocida» es información; decir «0.0.0» sería mentira.
DESCONOCIDA = "desconocida"


def app_version() -> str:
    """Versión del paquete instalado, o `desconocida` si no hay metadatos."""
    try:
        return metadata.version("tukul")
    except metadata.PackageNotFoundError:
        return DESCONOCIDA
    except Exception:  # metadatos corruptos o backend raro: nunca romper --health
        return DESCONOCIDA


def build_commit(raiz: Path | None = None) -> str:
    """Commit de la compilación: primero la variable de entorno, luego git.

    `TUKUL_COMMIT` gana porque en el binario distribuido no hay repositorio. Si
    no hay ninguno de los dos, devuelve cadena vacía (no un marcador: el
    llamador decide si lo muestra).

    Es deliberadamente silencioso ante cualquier fallo: un diagnóstico de salud
    no puede tumbar la aplicación por no encontrar `git`.
    """
    del_entorno = os.environ.get("TUKUL_COMMIT", "").strip()
    if del_entorno:
        return del_entorno[:40]

    directorio = raiz if raiz is not None else Path(__file__).resolve().parent.parent
    try:
        resultado = subprocess.run(
            ["git", "-C", str(directorio), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if resultado.returncode != 0:
        return ""
    return resultado.stdout.strip()[:40]


def identidad() -> str:
    """Una línea con versión y commit: lo que hay que pegar en un reporte."""
    version = app_version()
    commit = build_commit()
    return f"Tukul {version} ({commit})" if commit else f"Tukul {version}"
