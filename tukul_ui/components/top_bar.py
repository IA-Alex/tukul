from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable, Any
from tukul_ui import estilo as es
from tukul_ui.tooltip import ToolTip

class TopBar(ttk.Frame):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], menu: tk.Menu, state: Any, theme: str, **kwargs) -> None:
        super().__init__(parent, style="Cabecera.TFrame", padding=(es.ESP["sm"], es.ESP["xs"], es.ESP["sm"], es.ESP["xs"]), **kwargs)
        self.callbacks = callbacks
        self.menu = menu
        self.state = state
        self.theme = theme
        self._build()

    def _build(self) -> None:
        self.boton_menu = ttk.Menubutton(self, text="☰  Menú", menu=self.menu)
        self.boton_menu.pack(side="left")
        
        self.boton_guardar = ttk.Button(self, text="Guardar", style="Guardar.TButton", command=self.callbacks["save"])
        self.boton_guardar.pack(side="left", padx=(es.ESP["sm"], 0))
        
        self.references_button = ttk.Button(self, text="Contexto: 0 artículos", style="Plana.TButton", command=self.callbacks["manage_references"])
        self.references_button.pack(side="left", padx=(es.ESP["sm"], 0))

        self.sync_label = ttk.Label(self, text="○  Sin cambios", style="Cabecera.TLabel")
        self.sync_label.pack(side="left", padx=(es.ESP["lg"], 0))

        self.boton_panel = ttk.Button(self, text="◧  Ocultar panel IA  (F6)", command=self.callbacks["toggle_asistente"])
        self.boton_panel.pack(side="right")
        
        self.boton_tema = ttk.Button(self, style="Plana.TButton", command=self.callbacks["cambiar_tema"])
        self.boton_tema.pack(side="right", padx=(0, es.ESP["sm"]))
        
        self.profile_chip = ttk.Button(self, text=f"Modelo: {self.state.profile.model or 'sin configurar'}", style="Plana.TButton", command=self.callbacks["settings"])
        self.profile_chip.pack(side="right", padx=(0, es.ESP["sm"]))

        ToolTip(self.boton_menu, "Archivo: abrir, guardar y proyectos")
        ToolTip(self.boton_guardar, "Guardar el artículo (Ctrl+S)")
        ToolTip(self.references_button, "Gestionar los artículos de contexto")
        ToolTip(self.boton_panel, "Mostrar u ocultar el panel IA (F6)")
        self.tooltip_tema = ToolTip(self.boton_tema, "Cambiar de tema claro/oscuro")
        
        self.actualizar_estado(self.theme)

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
