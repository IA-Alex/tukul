"""Base compartida de los diálogos de Tukul.

Los diálogos de `dialogs.py`, `contexto_dialogo.py` e `ideas.py` repetían a
mano el mismo andamiaje: crear el `Toplevel`, fijar título/transient/fondo/
mínimo/geometría, atar Escape, configurar el `Listbox` con los mismos ocho
`kwargs` y volver a pintarlo al cambiar de tema. Las copias ya habían divergido
(dos mensajes distintos para la misma condición, DF-008), así que aquí vive la
fuente única.

El módulo no conoce ningún controlador: recibe la ventana padre por inyección.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from tukul_ui import estilo as es


def abrir_dialogo(
    parent: Any,
    titulo: str,
    *,
    fondo: str = es.SUPERFICIE,
    estilo_cuerpo: str = "Superficie.TFrame",
    modal: bool = False,
    minimo: tuple[int, int] | None = None,
    tamano: tuple[int, int] | None = None,
) -> tuple[tk.Toplevel, ttk.Frame]:
    """Crea un diálogo del sistema visual y devuelve (ventana, cuerpo).

    Centraliza fondo, padding de la rejilla, cierre con Escape y el
    dimensionado defensivo (recortado a la pantalla), para que los diálogos no
    vuelvan a divergir. `modal=True` activa el grab; el valor por defecto es no
    modal porque varios diálogos deben dejar leer el artículo de fondo.
    """
    raiz = parent.winfo_toplevel()
    dialogo = tk.Toplevel(parent)
    dialogo.title(titulo)
    dialogo.transient(raiz)
    dialogo.configure(bg=fondo)
    if modal:
        dialogo.grab_set()
    if minimo is not None:
        dialogo.minsize(*minimo)
    if tamano is not None:
        ancho, alto = tamano
        dialogo.geometry(es.tamano_ventana(
            ancho, alto, raiz.winfo_screenwidth(), raiz.winfo_screenheight(),
            minimo=minimo or (ancho, alto)))
    dialogo.bind("<Escape>", lambda _e: dialogo.destroy())
    cuerpo = ttk.Frame(dialogo, style=estilo_cuerpo, padding=es.ESP["lg"])
    cuerpo.pack(fill="both", expand=True)
    return dialogo, cuerpo


def crear_listbox(parent: tk.Misc, **extra) -> tk.Listbox:
    """`Listbox` con el vestido del sistema (sin repetir ocho colores cada vez).

    `extra` sobreescribe cualquier opción (p. ej. `selectmode` o `yscrollcommand`).
    """
    opciones: dict = {
        "exportselection": False,
        "background": es.SUPERFICIE_ALTA,
        "foreground": es.TEXTO,
        "selectbackground": es.SELECCION,
        "selectforeground": es.TEXTO,
        "relief": "flat",
        "highlightthickness": 1,
        "highlightbackground": es.BORDE_CONTROL,
        "highlightcolor": es.FOCO,
        "borderwidth": 0,
        "font": es.fuente(),
        "activestyle": "none",
    }
    opciones.update(extra)
    return tk.Listbox(parent, **opciones)


def reaplicar_tema_listbox(entries: tk.Listbox) -> None:
    """Repinta un `Listbox` al cambiar de tema (colores directos, no ttk)."""
    entries.configure(
        background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
        selectbackground=es.SELECCION, selectforeground=es.TEXTO,
        highlightbackground=es.BORDE_CONTROL, highlightcolor=es.FOCO,
    )


def registrar_reaplicar_tema(
    host: object, dialogo: Any, listbox: tk.Listbox | None = None,
) -> None:
    """Registra en el host el repintado del diálogo (y su lista, si la hay)."""
    registrar = getattr(host, "_registrar_reaplicar_tema", None)
    if registrar is None:
        return

    def _reaplicar() -> None:
        dialogo.configure(bg=es.SUPERFICIE)
        if listbox is not None:
            reaplicar_tema_listbox(listbox)

    registrar(dialogo, _reaplicar)


def wraplength_para(widget: Any, margen_lados: int | None = None) -> int:
    """Ancho de salto de línea que acompaña al ancho real del contenedor.

    Sustituye los `wraplength` fijos (300/320/380/520/580) que desbordaban o
    dejaban media columna vacía. Se redondea a la rejilla de espaciado para que
    el texto quede alineado con el resto del bloque.
    """
    lados = es.ESP["lg"] if margen_lados is None else margen_lados
    try:
        disponible = max(es.ESP["lg"] * 8, widget.winfo_width() - 2 * lados)
    except tk.TclError:
        disponible = es.ESP["lg"] * 8
    return int(disponible // es.ESP["xs"]) * es.ESP["xs"]


class SaltoDeLineaAdaptable:
    """Mantiene un conjunto de etiquetas con `wraplength` ligado al contenedor."""

    def __init__(self, contenedor: Any, etiquetas: tuple[Any, ...],
                 margen_lados: int | None = None) -> None:
        self._contenedor = contenedor
        self._etiquetas = etiquetas
        self._margen = margen_lados
        contenedor.bind("<Configure>", self._ajustar, add="+")

    def _ajustar(self, evento: Any = None) -> None:
        ancho = wraplength_para(self._contenedor, self._margen)
        for etiqueta in self._etiquetas:
            try:
                if int(float(etiqueta.cget("wraplength"))) != ancho:
                    etiqueta.config(wraplength=ancho)
            except (tk.TclError, ValueError):
                continue


# Alias tipográfico de conveniencia: los llamadores solo necesitan el callable.
Reaplicar = Callable[[], None]
