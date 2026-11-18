"""Control positivo: ¿el bus AT-SPI de este host ve una app GTK accesible?

Si `zenity` (GTK) aparece en el árbol y Tk no, el fallo de C3 es de **Tk**
(no implementa AT-SPI), no del entorno de verificación. Sin este control, un
«no aparece» podría atribuirse erróneamente al arnés.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def main() -> int:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    entorno = dict(os.environ, NO_AT_BRIDGE="0", GTK_MODULES="gail:atk-bridge")
    proc = subprocess.Popen(
        ["zenity", "--info", "--text=control", "--title=TK_CONTROL_GTK"],
        env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
            if nombres:
                print(f"intento {intento}: AT-SPI ve = {nombres}")
            if any("TK_CONTROL_GTK" in n or "zenity" in n.lower() for n in nombres):
                print("CONTROL POSITIVO OK: el bus AT-SPI ve una app GTK")
                return 0
            time.sleep(0.5)
        print("CONTROL POSITIVO FALLIDO: el bus AT-SPI no ve ni a zenity")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
