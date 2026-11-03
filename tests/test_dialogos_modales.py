"""Ningún diálogo modal puede bloquear la suite.

Un `messagebox` sin parchear detiene el test hasta que alguien pulsa Aceptar.
En una sesión interactiva pasa desapercibido; en CI el job se queda mudo. Así
ocurrió: `test_borrar_un_perfil_lo_quita_y_guardar_actualiza_la_app` llegaba a
`showerror` en el runner (sin llavero) y colgaba la ejecución 15 minutos.

La guarda convierte esa espera infinita en un fallo con nombre de test: se
sustituyen los diálogos por dobles que registran la llamada y devuelven una
respuesta por defecto, salvo que el propio test los parchee a propósito.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

DIALOGOS = ("showerror", "showinfo", "showwarning", "askyesno", "askokcancel")


@pytest.fixture(autouse=True)
def _sin_dialogos_modales():
    """Evita que un `messagebox` real espere a un clic que nunca llega.

    Devuelve valores neutros (True para las preguntas) y registra las llamadas
    en `_dialogos`, por si un test quiere comprobarlas sin parchear de nuevo.
    Si el test ya parcheó el mismo atributo, su parche tiene prioridad porque
    se aplica después.
    """
    llamadas: list[tuple[str, tuple, dict]] = []

    def doble(nombre: str):
        def registrar(*args, **kwargs):
            llamadas.append((nombre, args, kwargs))
            return True
        return registrar

    parches = [
        patch(f"tkinter.messagebox.{nombre}", doble(nombre))
        for nombre in DIALOGOS
    ]
    for parche in parches:
        parche.start()
    try:
        yield llamadas
    finally:
        for parche in reversed(parches):
            parche.stop()


def test_la_guarda_registra_las_llamadas(_sin_dialogos_modales):
    """La propia guarda se comporta: registra y no bloquea."""
    from tkinter import messagebox

    assert messagebox.askyesno("t", "m") is True
    assert ("askyesno", ("t", "m"), {}) in _sin_dialogos_modales
