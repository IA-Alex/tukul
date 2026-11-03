from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from tukul_ui import estilo as es
from tukul_ui.tooltip import ToolTip

if TYPE_CHECKING:  # evita el import circular: app importa TopBar
    from tukul_ui.app import TukulApp


class TopBar(ttk.Frame):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], menu: tk.Menu, state: Any, theme: str, **kwargs) -> None:
        super().__init__(parent, style="Cabecera.TFrame", padding=(es.ESP["sm"], es.ESP["xs"], es.ESP["sm"], es.ESP["xs"]), **kwargs)
        self.callbacks = callbacks
        self.menu = menu
        # La barra consulta el perfil activo de la app: `state` es la propia
        # aplicación, no un widget genérico (sin tipar, mypy confundía
        # `state.profile` con el `pack_slaves` heredado de Tk).
        self.app: TukulApp = state
        self.theme = theme
        self._build()

    def _build(self) -> None:
        self.boton_menu = ttk.Menubutton(self, text="☰  Menú", menu=self.menu)
        self.boton_menu.pack(side="left")

        self.boton_guardar = ttk.Button(self, text="Guardar", style="Guardar.TButton", command=self.callbacks["save"])
        self.boton_guardar.pack(side="left", padx=(es.ESP["sm"], 0))
        # «Guardar» depende de un documento y de Ctrl+S: fuera del recorrido
        # con Tab para que este empiece por Menú (navegación, nunca destructiva)
        # y no por una acción que aparece pesada pero no aplica aún.
        self.boton_guardar.configure(takefocus=False)
        self.boton_guardar.configure(cursor="hand2")

        self.references_button = ttk.Button(self, text="Contexto: 0 artículos", style="Plana.TButton", command=self.callbacks["manage_references"])
        self.references_button.pack(side="left", padx=(es.ESP["sm"], 0))

        self.sync_label = ttk.Label(self, text="◌  Sin cambios", style="Cabecera.TLabel")
        self.sync_label.pack(side="left", padx=(es.ESP["lg"], 0))

        # Nombre del artículo. La ventana solo dice «Tukul»: con dos o tres
        # artículos abiertos en el día no había forma de saber cuál está activo
        # sin leer el historial. Se recorta, nunca se desborda ni empuja a los
        # controles de la derecha.
        self.documento_var = tk.StringVar(value="")
        self.documento_label = ttk.Label(self, textvariable=self.documento_var,
                                         style="Cabecera.TLabel", anchor="w")
        self.documento_label.pack(side="left", padx=(es.ESP["md"], 0), fill="x", expand=True)
        ToolTip(self.documento_label, "Documento activo")

        self.boton_panel = ttk.Button(self, text="◧  Ocultar panel IA  (F6)", command=self.callbacks["toggle_asistente"])
        self.boton_panel.pack(side="right")

        self.boton_tema = ttk.Button(self, style="Plana.TButton", command=self.callbacks["cambiar_tema"])
        self.boton_tema.pack(side="right", padx=(0, es.ESP["sm"]))

        self.profile_chip = ttk.Button(self, text=f"Modelo: {self.app.profile.model or 'sin configurar'}", style="Plana.TButton", command=self.callbacks["settings"])
        self.profile_chip.pack(side="right", padx=(0, es.ESP["sm"]))

        self.boton_menu.configure(cursor="hand2")

        ToolTip(self.boton_menu, "Archivo: abrir, guardar y proyectos")
        ToolTip(self.boton_guardar, "Guardar el artículo (Ctrl+S)")
        ToolTip(self.references_button, "Gestionar los artículos de contexto")
        ToolTip(self.boton_panel, "Mostrar u ocultar el panel IA (F6)")
        self.tooltip_tema = ToolTip(self.boton_tema, "Cambiar de tema claro/oscuro")

        self.actualizar_estado(self.theme)

    def actualizar_documento(self, nombre: str | None) -> None:
        """Muestra el artículo activo; sin documento no ocupa espacio."""
        if not nombre:
            self.documento_var.set("")
            return
        limite = 42
        visible = nombre if len(nombre) <= limite else nombre[: limite - 1] + "…"
        self.documento_var.set(visible)

    def actualizar_estado(self, theme: str) -> None:
        self.theme = theme
        if self.theme == "light":
            etiqueta = "☾  Cambiar a oscuro"
            tooltip = "Cambiar a tema oscuro (actual: claro)"
        else:
            etiqueta = "☀  Cambiar a claro"
            tooltip = "Cambiar a tema claro (actual: oscuro)"
        self.boton_tema.config(text=etiqueta)
        self.tooltip_tema.set_texto(tooltip)
