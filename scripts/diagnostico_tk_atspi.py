"""Diagnóstico: ¿Tk expone una ventana básica en el árbol AT-SPI?

Separa la pregunta «¿Tk es accesible por AT-SPI en este host?» de
«¿Tukul registra su ventana?». Si una ventana Tk mínima no aparece, el
problema es del entorno (falta el puente), no de la app.
"""
from __future__ import annotations

import subprocess
import sys
import time

CODIGO_TK = """
import tkinter as tk
from tkinter import ttk
raiz = tk.Tk()
raiz.title("VENTANA_DIAGNOSTICO_TK")
ttk.Label(raiz, text="hola").pack()
texto = tk.Text(raiz)
texto.pack()
raiz.update()
import time
fin = time.time() + 20
while time.time() < fin:
    raiz.update()
    time.sleep(0.05)
"""


def main() -> int:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    proc = subprocess.Popen(
        [sys.executable, "-c", CODIGO_TK],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        escritorio = Atspi.get_desktop(0)
        for intento in range(20):
            nombres = []
            for i in range(escritorio.get_child_count()):
                app = escritorio.get_child_at_index(i)
                if app is None:
                    continue
                try:
                    nombres.append(app.get_name() or "")
                except Exception:
                    pass
            print(f"intento {intento}: aplicaciones en AT-SPI = {nombres}")
            if any("DIAGNOSTICO" in n for n in nombres):
                print("Tk SÍ aparece en AT-SPI")
                return 0
            time.sleep(0.5)
        print("Tk NO aparece en AT-SPI con esta configuración de entorno")
        print(f"NO_AT_BRIDGE={__import__('os').environ.get('NO_AT_BRIDGE')!r}")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
