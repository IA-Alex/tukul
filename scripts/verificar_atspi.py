"""Verificación C3: ¿Tukul expone un árbol de accesibilidad usable por AT-SPI?

No forma parte de la suite: necesita un bus AT-SPI y `gi` del sistema, que no
están en CI. Es la evidencia que faltaba para C3 (lector de pantalla).

Uso:
    dbus-run-session -- xvfb-run -a /usr/bin/python3 scripts/verificar_atspi.py

Lanza Tukul, espera a que registre su ventana en AT-SPI y recorre el árbol
buscando los elementos que un lector de pantalla necesita: la ventana, el
editor de texto y el panel del asistente.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _conectar_atspi():
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return Atspi


def _recorrer(nodo, nivel=0, acumulado=None, maximo=40):
    """Recorre el árbol accesible acumulando (rol, nombre)."""
    if acumulado is None:
        acumulado = []
    if len(acumulado) >= maximo:
        return acumulado
    try:
        rol = nodo.get_role_name()
        nombre = nodo.get_name() or ""
        acumulado.append((nivel, rol, nombre))
        for i in range(nodo.get_child_count()):
            hijo = nodo.get_child_at_index(i)
            if hijo is not None:
                _recorrer(hijo, nivel + 1, acumulado, maximo)
    except Exception as error:  # pragma: no cover - diagnóstico
        acumulado.append((nivel, "ERROR", str(error)))
    return acumulado


def _buscar_ventana(atspi, titulo_parcial: str, intentos: int = 20):
    """Espera a que aparezca la ventana de Tukul en el escritorio accesible."""
    escritorio = atspi.get_desktop(0)
    for _ in range(intentos):
        for i in range(escritorio.get_child_count()):
            app = escritorio.get_child_at_index(i)
            if app is None:
                continue
            try:
                nombre = app.get_name() or ""
            except Exception:
                continue
            if titulo_parcial.lower() in nombre.lower():
                return app
        time.sleep(0.5)
    return None


def main() -> int:
    try:
        atspi = _conectar_atspi()
    except Exception as error:
        print(f"C3 NO VERIFICADO: no se pudo cargar AT-SPI ({error})")
        return 2

    # Lanzar Tukul en el mismo display. Tk publica en AT-SPI a través del
    # puente de ATK: sin `atk-bridge` cargado, la app no aparece en el árbol.
    entorno = dict(os.environ)
    entorno.setdefault("NO_AT_BRIDGE", "0")
    entorno["GTK_MODULES"] = "gail:atk-bridge"
    entorno["GTK_MODULES"] = entorno.get("GTK_MODULES", "gail:atk-bridge")
    proceso = subprocess.Popen(
        [str(RAIZ / ".venv" / "bin" / "python"), str(RAIZ / "tukul.py")],
        cwd=str(RAIZ), env=entorno,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        app = _buscar_ventana(atspi, "Tukul")
        if app is None:
            print("C3 NO VERIFICADO: la app no apareció en el árbol AT-SPI")
            return 3

        print(f"Ventana encontrada en AT-SPI: {app.get_name()!r}")
        arbol = _recorrer(app)
        print(f"Elementos accesibles detectados: {len(arbol)}")
        for nivel, rol, nombre in arbol[:30]:
            print(f"  {'  ' * nivel}{rol}: {nombre!r}")

        roles = {rol for _n, rol, _nom in arbol}
        texto_roles = {"text", "entry", "document text", "edit bar", "text area"}
        tiene_texto = bool(roles & texto_roles)
        print(f"\n¿Expone un widget de texto? {'SÍ' if tiene_texto else 'NO'}")
        print(f"Roles presentes: {sorted(roles)}")
        return 0 if tiene_texto else 4
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()


if __name__ == "__main__":
    sys.exit(main())
