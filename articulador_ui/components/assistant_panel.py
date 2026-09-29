from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable, Any
from articulador_ui import estilo as es
from articulador_ui.estado import EstadoUI

class AssistantPanel(ttk.Labelframe):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], **kwargs) -> None:
        super().__init__(parent, text="ASISTENTE", padding=es.ESP["md"], **kwargs)
        self.callbacks = callbacks
        self._build()

    def _build(self) -> None:
        # ... (compositor, historial, fila acciones, rótulos de estado)
        # (Preservando código existente...)
        self.compositor = ttk.Frame(self, style="Alta.TFrame", padding=es.ESP["xs"])
        self.compositor.pack(side="bottom", fill="x")
        
        self.send_button = ttk.Button(self.compositor, text="Enviar", style="Primaria.TButton",
                                      command=self.callbacks["send_message"])
        self.send_button.pack(side="right", fill="y")
        
        self.input = self.callbacks["create_input"](self.compositor)
        self.input.pack(side="left", fill="both", expand=True, padx=(0, es.ESP["xs"]))

        self.history = self.callbacks["create_history"](self)
        self.history.pack(fill="both", expand=True)

        self.fila_acciones = ttk.Frame(self, style="Superficie.TFrame")
        self.fila_acciones.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))
        
        self.cancel_button = ttk.Button(self.fila_acciones, text="Cancelar", 
                                        command=self.callbacks["cancel_request"], state="disabled")
        self.cancel_button.pack(side="right", padx=(0, es.ESP["sm"]))
        self.review_button = ttk.Button(self.fila_acciones, text="Revisar artículo", 
                                        command=self.callbacks["review"])
        self.review_button.pack(side="left")

        self.estado_label = ttk.Label(self, style="Superficie.TLabel")
        self.estado_label.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))
        
        self.estado_ayuda = ttk.Label(self, style="TenueSuperficie.TLabel",
                                      wraplength=300, justify="left")
        self.estado_ayuda.pack(side="bottom", fill="x", pady=(2, es.ESP["sm"]))
        
        self.cost_label = ttk.Label(self, style="TenueSuperficie.TLabel",
                                    wraplength=300, justify="left")
        self.cost_label.pack(side="bottom", fill="x", pady=(es.ESP["xs"], 0))

        # --- BARRA DE APROBACIÓN INTEGRADA ---
        self.barra_aprobacion = ttk.Frame(self, style="Alta.TFrame",
                                          padding=(es.ESP["sm"], es.ESP["sm"]))
        self.aprobacion_texto = tk.StringVar(value="")
        self.aprobacion_label = ttk.Label(self.barra_aprobacion,
                                          textvariable=self.aprobacion_texto,
                                          background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                                          font=es.fuente(es.TIPO_SM), wraplength=300,
                                          justify="left")
        self.aprobacion_label.pack(fill="x")
        acciones = ttk.Frame(self.barra_aprobacion, style="Alta.TFrame")
        acciones.pack(fill="x", pady=(es.ESP["sm"], 0))
        self.boton_aprobar = ttk.Button(acciones, text="Enviar artículos",
                                        style="Primaria.TButton")
        self.boton_aprobar.pack(side="right")
        self.boton_rechazar = ttk.Button(acciones, text="No enviar")
        self.boton_rechazar.pack(side="right", padx=(0, es.ESP["sm"]))
        # Oculta inicialmente
        self.barra_aprobacion.pack_forget()

    def show_approval(self, text: str, on_approve: Callable, on_reject: Callable):
        self.aprobacion_texto.set(text)
        self.boton_aprobar.config(command=on_approve)
        self.boton_rechazar.config(command=on_reject)
        self.barra_aprobacion.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0), before=self.estado_label)
        self.boton_aprobar.focus_set()

    def hide_approval(self):
        if self.barra_aprobacion.winfo_ismapped():
            self.barra_aprobacion.pack_forget()
