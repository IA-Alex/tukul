"""Configuración de pytest para el proyecto.

Además de poner la raíz en `sys.path`, este archivo protege la sesión gráfica
del usuario. La suite monta ventanas Tk reales (miles de ciclos de `update()`
entre ~400 tests) para probar estados, foco y teclado reales. Si eso corre
sobre el display del usuario, el gestor de ventanas recibe una avalancha de
eventos MAP/FOCUS: la ventana aparece cientos de veces y le roba el teclado.

Por eso:

- Con `xvfb-run` (lo que hacen `scripts/quality-gate.sh` y CI) hay un display
  virtual: los tests con Tk corren completos y nada se dibuja en pantalla.
- Sin display virtual pero con `DISPLAY` real, la suite se niega a arrancar y
  explica cómo correrla de forma segura, en vez de invadir la sesión.
- Se puede forzar el modo inseguro con `TUKUL_TESTS_DISPLAY_REAL=1`.

Los tests con Tk se saltan solos cuando no hay display (ver `_hay_display`).
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

#: Marca que deja `xvfb-run -a` en el display (Xvfb numera desde :90 en la
#: práctica) o que un arnés equivalente exporta a propósito.
_XVFB_ENV = "TUKUL_TESTS_XVFB"


def _display_es_virtual(display: str) -> bool:
    """Xvfb suele servir `:99` en adelante; los servidores reales, `:0`."""
    try:
        numero = int(display.lstrip(":").split(".")[0])
    except ValueError:
        # Formas como `host:0` u opacas: no se puede afirmar que sea virtual.
        return False
    return numero >= 90


def _bloquear_display_real() -> None:
    if os.environ.get("TUKUL_TESTS_DISPLAY_REAL") == "1":
        return  # El usuario pidió explícitamente el modo invasivo.
    display = os.environ.get("DISPLAY", "")
    if not display or os.environ.get(_XVFB_ENV) == "1" or _display_es_virtual(display):
        return  # Sin display (los tests con Tk se omiten) o uno virtual: seguro.
    sys.stderr.write(
        "\n"
        "ERROR: la suite abriría ventanas Tkinter en tu escritorio real\n"
        f"       (DISPLAY={display}). Eso roba el foco del teclado cientos de\n"
        "       veces mientras dura la ejecución.\n"
        "\n"
        "       Ejecútala con un display virtual:\n"
        "\n"
        "           xvfb-run -a .venv/bin/python -m pytest -q\n"
        "\n"
        "       O el gate completo, que ya lo hace:\n"
        "\n"
        "           ./scripts/quality-gate.sh\n"
        "\n"
        "       Si de verdad quieres ventanas visibles:\n"
        "\n"
        "           TUKUL_TESTS_DISPLAY_REAL=1 python -m pytest -q\n"
        "\n",
    )
    raise SystemExit(2)


_bloquear_display_real()
