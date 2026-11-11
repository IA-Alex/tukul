from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from tukul_ui import estilo as es
from tukul_ui.tooltip import ToolTip


class AssistantPanel(ttk.Labelframe):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], **kwargs) -> None:
        super().__init__(parent, text="ASISTENTE", padding=es.ESP["md"], **kwargs)
        self.callbacks = callbacks
        self._build()

    def _build(self) -> None:
        # Orden de `pack` deliberado: con pack, lo que se coloca DESPUÉS se
        # recorta primero cuando falta espacio. Por eso los controles de abajo
        # (compositor, acciones, estados, barra de aprobación) se reservan ANTES
        # que el historial expansible. Antes el historial iba primero y con el
        # panel corto la barra de aprobación quedaba en 1 px de alto.
        self.compositor = ttk.Frame(self, style="Alta.TFrame", padding=es.ESP["xs"])
        self.compositor.pack(side="bottom", fill="x")

        self.send_button = ttk.Button(self.compositor, text="Enviar", style="Primaria.TButton",
                                      command=self.callbacks["send_message"])
        self.send_button.pack(side="right", fill="y")
        self.tooltip_enviar = ToolTip(
            self.send_button,
            "Envía la consulta usando el artículo activo, la selección y el contexto aprobado.",
        )

        self.input = self.callbacks["create_input"](self.compositor)
        self.input.pack(side="left", fill="both", expand=True, padx=(0, es.ESP["xs"]))

        self.fila_acciones = ttk.Frame(self, style="Superficie.TFrame")
        self.fila_acciones.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))

        # Nace inactivo pero visible (estilo «Inactivo», sin relieve): se
        # descubre que se puede cancelar sin que parezca un botón roto.
        self.cancel_button = ttk.Button(self.fila_acciones, text="Cancelar",
                                        style="Inactivo.TButton",
                                        command=self.callbacks["cancel_request"], state="disabled")
        self.cancel_button.pack(side="right", padx=(0, es.ESP["sm"]))
        self.review_button = ttk.Button(self.fila_acciones, text="Revisar artículo",
                                        command=self.callbacks["review"])
        self.review_button.pack(side="left")
        # «Revisar artículo» nombra una acción con consecuencia sobre el texto:
        # el alcance es la primera duda. El globo responde a las tres preguntas
        # que frenaban el clic: qué revisa, sobre qué, y si modifica el artículo.
        ToolTip(self.review_button,
                "Revisa ortografía, gramática, semántica y estructura del artículo "
                "completo o de la selección. No modifica nada: propone cambios uno a uno.")

        self.estado_label = ttk.Label(self, style="Superficie.TLabel")
        self.estado_label.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))

        self.estado_ayuda = ttk.Label(self, style="TenueSuperficie.TLabel",
                                      wraplength=300, justify="left")
        self.estado_ayuda.pack(side="bottom", fill="x", pady=(2, es.ESP["sm"]))

        self.cost_label = ttk.Label(self, style="TenueSuperficie.TLabel",
                                    wraplength=300, justify="left")
        self.cost_label.pack(side="bottom", fill="x", pady=(es.ESP["xs"], 0))

        # El historial es lo único expansible: va al final para ceder espacio
        # antes que cualquier control.
        self.history = self.callbacks["create_history"](self)
        self.history.pack(fill="both", expand=True)

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

        # Los tres textos que se justifican a la izquierda iban con un
        # `wraplength` fijo de 300 px: en un panel ancho dejaban media columna
        # vacía y en uno estrecho desbordaban. Ahora el salto acompaña al ancho
        # real del panel y el bloque queda alineado con el compositor.
        self._textos_ajustables = (self.estado_ayuda, self.cost_label, self.aprobacion_label)
        self.bind("<Configure>", self._ajustar_salto_de_linea)

    def _ajustar_salto_de_linea(self, event: tk.Event) -> None:
        """Recalcula el ancho de texto según el panel (rejilla de 4)."""
        disponible = max(es.ESP["lg"] * 8, event.width - 2 * es.ESP["md"])
        ancho = int(disponible // es.ESP["xs"]) * es.ESP["xs"]
        for etiqueta in self._textos_ajustables:
            if int(float(etiqueta.cget("wraplength"))) != ancho:
                etiqueta.config(wraplength=ancho)

    def show_approval(self, text: str, on_approve: Callable, on_reject: Callable) -> None:
        self.aprobacion_texto.set(text)
        self.boton_aprobar.config(command=on_approve)
        self.boton_rechazar.config(command=on_reject)
        self.barra_aprobacion.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0), before=self.estado_label)
        self.boton_aprobar.focus_set()

    def hide_approval(self) -> None:
        if self.barra_aprobacion.winfo_ismapped():
            self.barra_aprobacion.pack_forget()
