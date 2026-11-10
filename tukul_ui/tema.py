"""Sistema visual ttk de Tukul, en un solo lugar.

`aplicar_estilos` configura todos los estilos ttk y las opciones Tk derivadas
del tema activo. Es la parte de `TukulApp._theme` que no depende del estado de
la aplicación: el resto (reaplicar colores directos a los widgets ya creados)
vive en la app, que es quien conoce sus widgets.

Extraerlo mantiene `app.py` enfocado en coordinar y permite razonar el tema sin
abrir la ventana completa.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from tukul_ui import estilo as es


def aplicar_estilos(raiz: tk.Tk, tema: str, reaplicar_widgets: Callable[[], None]) -> None:
    """Aplica el sistema visual del tema activo: un fondo, dos superficies.

    Los estilos ttk se repintan en bloque; los widgets Tk con colores directos
    los repinta `reaplicar_widgets`, que la app implementa porque es la dueña de
    sus widgets (no se destruye ni se recrea nada).

    Args:
        raiz: ventana raíz, para `ttk.Style` y `option_add`.
        tema: nombre del tema (`dark` o `light`), ya validado por la app.
        reaplicar_widgets: callback que reaplica colores directos a los widgets
            Tk ya creados.
    """
    es.aplicar_tema(tema)
    raiz.configure(bg=es.FONDO)
    style = ttk.Style(raiz)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=es.FONDO, foreground=es.TEXTO, font=es.fuente(),
                    focuscolor=es.FOCO)
    style.configure("TFrame", background=es.FONDO)
    style.configure("Cabecera.TFrame", background=es.SUPERFICIE_ALTA)
    style.configure("Superficie.TFrame", background=es.SUPERFICIE)
    style.configure("Alta.TFrame", background=es.SUPERFICIE_ALTA)
    style.configure("TLabel", background=es.FONDO, foreground=es.TEXTO)
    style.configure("Superficie.TLabel", background=es.SUPERFICIE, foreground=es.TEXTO)
    style.configure("Tenue.TLabel", background=es.FONDO, foreground=es.TEXTO_TENUE,
                    font=es.fuente(es.TIPO_SM))
    style.configure("TenueSuperficie.TLabel", background=es.SUPERFICIE,
                    foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM))
    style.configure("Titulo.TLabel", background=es.SUPERFICIE, foreground=es.TEXTO,
                    font=es.fuente(negrita=True))
    # Franja inferior: continua, tenue y de una sola pieza.
    style.configure("Cabecera.TLabel", background=es.SUPERFICIE_ALTA,
                    foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM))
    # Separador de la cabecera: divisoria fina que separa acciones de
    # configuración. Usa `borde` (sutil), no `borde_control`: no se pulsa.
    style.configure("Cabecera.TSeparator", background=es.BORDE)
    style.map("Cabecera.TSeparator", background=[("!disabled", es.BORDE)])
    style.configure("Pie.TFrame", background=es.SUPERFICIE)
    style.configure("Pie.TLabel", background=es.SUPERFICIE, foreground=es.TEXTO_TENUE,
                    font=es.fuente(es.TIPO_SM))
    # El divisor es una señal de ajuste, no un borde de panel dominante.
    # `sashthickness` fija la zona sensible al arrastre: por debajo de 4 px
    # el agarre se vuelve incómodo, así que se mantiene fino pero usable.
    # El sash es una pieza accionable (se arrastra): 1.4.11 le exige 3:1,
    # así que usa `BORDE_CONTROL` y no la divisoria discreta.
    style.configure("TPanedwindow", background=es.BORDE)
    style.configure("Sash", background=es.BORDE_CONTROL, bordercolor=es.BORDE_CONTROL,
                    sashthickness=4, gripcount=0, lightcolor=es.BORDE_CONTROL,
                    darkcolor=es.BORDE_CONTROL)
    # Paneles sin marco: la separación la dan la superficie y el divisor.
    style.configure("TLabelframe", background=es.SUPERFICIE,
                    bordercolor=es.SUPERFICIE, relief="flat", borderwidth=0)
    style.configure("TLabelframe.Label", background=es.SUPERFICIE,
                    foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM, negrita=True))

    # Estados unificados de los controles. Cuatro señales, siempre las mismas:
    #   reposo  -> superficie elevada
    #   hover   -> un escalón más claro (borde)
    #   pulsado -> vuelve a la superficie base, con el borde en foco
    #   inhabilitado -> fondo hundido Y texto tenue (no solo color: el
    #                   contraste baja, y ttk además ignora el clic)
    # El hover usa una superficie propia: usar BORDE obligaba a que esta
    # divisoria fuera fondo de botón, y entonces su contraste quedaba
    # atado al del texto (ver `borde`/`borde_control` en `estilo.py`).
    estados_fondo = [("disabled", es.SUPERFICIE), ("pressed", es.SUPERFICIE),
                     ("active", es.SUPERFICIE_ACTIVA)]
    estados_texto = [("disabled", es.TEXTO_TENUE)]
    estados_borde = [("focus", es.FOCO), ("pressed", es.FOCO),
                     ("disabled", es.SUPERFICIE)]
    style.configure("TButton", background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                    bordercolor=es.BORDE_CONTROL, focuscolor=es.FOCO, relief="flat",
                    padding=(es.ESP["sm"], es.ESP["xs"] + 1))
    style.map("TButton", background=estados_fondo, foreground=estados_texto,
              bordercolor=estados_borde)
    style.configure("Primaria.TButton", background=es.ACENTO, foreground=es.ACENTO_TEXTO,
                    bordercolor=es.ACENTO, focuscolor=es.ACENTO_TEXTO, relief="flat",
                    font=es.fuente(negrita=True), padding=(es.ESP["md"], es.ESP["xs"] + 2))
    style.map("Primaria.TButton",
              background=[("disabled", es.SUPERFICIE_ALTA), ("pressed", es.ACENTO),
                          ("active", es.ACENTO_ACTIVO)],
              foreground=[("disabled", es.TEXTO_TENUE)],
              bordercolor=[("focus", es.ACENTO_TEXTO), ("disabled", es.SUPERFICIE_ALTA)])
    style.configure("Guardar.TButton", background=es.SUPERFICIE_ALTA,
                    foreground=es.TEXTO, bordercolor=es.BORDE_CONTROL, relief="flat",
                    focuscolor=es.FOCO, font=es.fuente(negrita=True),
                    padding=(es.ESP["sm"], es.ESP["xs"] + 1))
    style.map("Guardar.TButton", background=estados_fondo, foreground=estados_texto,
              bordercolor=estados_borde)
    # «Cancelar» en reposo: se queda visible (así se descubre la salida)
    # pero sin relieve ni borde, como una palabra y no como un botón
    # apagado. Deshabilitado no dice «Revisar está roto»: dice «aquí no hay
    # nada que cancelar». Al haber una consulta vuelve el botón normal.
    style.configure("Inactivo.TButton", background=es.SUPERFICIE,
                    foreground=es.TEXTO_TENUE, bordercolor=es.SUPERFICIE,
                    lightcolor=es.SUPERFICIE, darkcolor=es.SUPERFICIE,
                    relief="flat", focuscolor=es.SUPERFICIE,
                    font=es.fuente(es.TIPO_MD),
                    padding=(es.ESP["sm"], es.ESP["xs"] + 1))
    style.map("Inactivo.TButton",
              background=[("disabled", es.SUPERFICIE)],
              foreground=[("disabled", es.TEXTO_TENUE)],
              bordercolor=[("disabled", es.SUPERFICIE)],
              lightcolor=[("disabled", es.SUPERFICIE)],
              darkcolor=[("disabled", es.SUPERFICIE)])
    style.configure("Plana.TButton", background=es.SUPERFICIE, foreground=es.TEXTO_TENUE,
                    bordercolor=es.SUPERFICIE, relief="flat", focuscolor=es.FOCO,
                    font=es.fuente(es.TIPO_SM), padding=(es.ESP["sm"], es.ESP["xs"]))
    style.map("Plana.TButton",
              background=[("disabled", es.SUPERFICIE), ("pressed", es.SUPERFICIE),
                          ("active", es.SUPERFICIE_ALTA)],
              foreground=[("disabled", es.BORDE), ("active", es.TEXTO)],
              bordercolor=[("focus", es.FOCO)])
    style.configure("TMenubutton", background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                    focuscolor=es.FOCO, relief="flat",
                    padding=(es.ESP["sm"], es.ESP["xs"] + 1))
    style.map("TMenubutton", background=estados_fondo, foreground=estados_texto)
    style.configure("TCheckbutton", background=es.SUPERFICIE, foreground=es.TEXTO,
                    focuscolor=es.FOCO)
    style.map("TCheckbutton", background=[("active", es.SUPERFICIE)],
              foreground=estados_texto)
    # Los campos de los diálogos salían en blanco: ttk.Entry y ttk.Combobox
    # no heredan del estilo raíz y rompían el conjunto oscuro.
    for campo in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(campo, fieldbackground=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                        background=es.SUPERFICIE_ALTA, bordercolor=es.BORDE_CONTROL,
                        lightcolor=es.BORDE_CONTROL, darkcolor=es.BORDE_CONTROL,
                        arrowcolor=es.TEXTO_TENUE, insertcolor=es.ACENTO,
                        selectbackground=es.SELECCION, selectforeground=es.TEXTO)
        style.map(campo,
                  fieldbackground=[("readonly", es.SUPERFICIE_ALTA),
                                   ("disabled", es.SUPERFICIE)],
                  foreground=[("disabled", es.TEXTO_TENUE)],
                  bordercolor=[("focus", es.FOCO)])
    # El desplegable del Combobox es un Listbox de Tk: solo obedece a la
    # base de datos de opciones.
    raiz.option_add("*TCombobox*Listbox.background", es.SUPERFICIE_ALTA)
    raiz.option_add("*TCombobox*Listbox.foreground", es.TEXTO)
    raiz.option_add("*TCombobox*Listbox.selectBackground", es.SELECCION)
    raiz.option_add("*TCombobox*Listbox.selectForeground", es.TEXTO)
    # Las barras de desplazamiento por defecto son claras y rompen el conjunto.
    style.configure("Vertical.TScrollbar", background=es.SUPERFICIE_ALTA,
                    troughcolor=es.SUPERFICIE, bordercolor=es.SUPERFICIE,
                    arrowcolor=es.TEXTO_TENUE, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", es.BORDE_CONTROL)])
    style.configure("Horizontal.TScrollbar", background=es.SUPERFICIE_ALTA,
                    troughcolor=es.SUPERFICIE, bordercolor=es.SUPERFICIE,
                    arrowcolor=es.TEXTO_TENUE, relief="flat")
    reaplicar_widgets()
