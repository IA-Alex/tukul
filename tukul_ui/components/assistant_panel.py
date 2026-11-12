from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from tukul_ui import estilo as es
from tukul_ui.tooltip import ToolTip


class AssistantPanel(ttk.Labelframe):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], **kwargs) -> None:
        super().__init__(parent, text="Asistente", padding=(es.ESP["md"], es.ESP["sm"], es.ESP["md"], es.ESP["md"]), **kwargs)
        self.callbacks = callbacks
        self._build()

    def _build(self) -> None:
        self.guia = ttk.Frame(self, style="Superficie.TFrame")
        self.guia.pack(side="top", fill="x", pady=(0, es.ESP["sm"]))
        ttk.Label(self.guia, text="Tu compañero de escritura",
                  style="PanelTitulo.TLabel").pack(anchor="w")
        ttk.Label(self.guia,
                  text="Pregunta sobre el artículo, una selección o su estructura.",
                  style="PanelMeta.TLabel", wraplength=520, justify="left").pack(
                      anchor="w", pady=(2, 0))

        # Orden de `pack` deliberado: con pack, lo que se coloca DESPUÉS se
        # recorta primero cuando falta espacio. Por eso los controles de abajo
        # (compositor, acciones, estados, barra de aprobación) se reservan ANTES
        # que el historial expansible. Antes el historial iba primero y con el
        # panel corto la barra de aprobación quedaba en 1 px de alto.
        self.compositor = ttk.Frame(self, style="Alta.TFrame", padding=(es.ESP["sm"], es.ESP["sm"], es.ESP["sm"], es.ESP["xs"]))
        self.compositor.pack(side="bottom", fill="x")

        # El asa vive ARRIBA del campo, como una frontera que se puede
        # arrastrar. Antes estaba fuera y debajo del compositor: se veía como
        # una línea decorativa y no como el control que cambia su tamaño.
        self.resize_handle = ttk.Frame(self.compositor, style="ResizeHandle.TFrame",
                                       height=es.ESP["sm"], cursor="sb_v_double_arrow")
        self.resize_handle.pack(side="top", fill="x", pady=(0, es.ESP["xs"]))
        ToolTip(self.resize_handle, "Arrastra para ampliar el campo de mensaje")

        self.composer_row = ttk.Frame(self.compositor, style="Alta.TFrame")
        self.composer_row.pack(side="top", fill="x")

        self.send_button = ttk.Button(self.composer_row, text="Enviar", style="Primaria.TButton",
                                      command=self.callbacks["send_message"])
        self.send_button.pack(side="right", fill="y")
        self.tooltip_enviar = ToolTip(
            self.send_button,
            "Envía la consulta usando el artículo activo, la selección y el contexto aprobado.",
        )

        self.input = self.callbacks["create_input"](self.composer_row)
        self.input.pack(side="left", fill="both", expand=True, padx=(0, es.ESP["xs"]))

        # El compositor deja de ser una caja fija de tres líneas y puede crecer
        # hasta ocupar una parte sustancial del panel.
        self._resize_y: int | None = None
        self._resize_height = 3
        self.resize_handle.bind("<Button-1>", self._iniciar_resize_input)
        self.resize_handle.bind("<B1-Motion>", self._mover_resize_input)
        self.resize_handle.bind("<ButtonRelease-1>", self._terminar_resize_input)

        self.fila_acciones = ttk.Frame(self, style="Superficie.TFrame")
        self.fila_acciones.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))

        # Nace oculto: solo aparece cuando existe una petición cancelable.
        # Así «Respuesta completa» no deja un botón visible que ya no puede actuar.
        self.cancel_button = ttk.Button(self.fila_acciones, text="Cancelar",
                                        style="Inactivo.TButton",
                                        command=self.callbacks["cancel_request"], state="disabled")
        self.cancel_button.pack(side="right", padx=(0, es.ESP["sm"]))
        self.review_button = ttk.Button(self.fila_acciones, text="Revisar artículo",
                                        style="Secundaria.TButton",
                                        command=self.callbacks["review"])
        self.review_button.pack(side="left")
        # «Revisar artículo» nombra una acción con consecuencia sobre el texto:
        # el alcance es la primera duda. El globo responde a las tres preguntas
        # que frenaban el clic: qué revisa, sobre qué, y si modifica el artículo.
        ToolTip(self.review_button,
                "Revisa ortografía, gramática, semántica y estructura del artículo "
                "completo o de la selección. No modifica nada: propone cambios uno a uno.")

        self.estado_label = ttk.Label(self, style="Superficie.TLabel",
                                      font=es.fuente(es.TIPO_SM, negrita=True))
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

    def _iniciar_resize_input(self, evento: tk.Event) -> None:
        """Guarda el punto de inicio del arrastre vertical del compositor."""
        self._resize_y = int(evento.y_root)
        try:
            self._resize_height = max(3, int(self.input.cget("height")))
        except (tk.TclError, TypeError, ValueError):
            self._resize_height = 3

    def _mover_resize_input(self, evento: tk.Event) -> None:
        """Ajusta la altura del campo mientras se arrastra el asa."""
        if self._resize_y is None:
            return
        delta = self._resize_y - int(evento.y_root)
        # Una línea de Tk ronda 18 px: el cambio se siente continuo sin saltos.
        lineas = self._resize_height + round(delta / 18)
        limite = max(8, min(40, self.winfo_height() // 18))
        try:
            self.input.configure(height=max(3, min(limite, lineas)))
        except tk.TclError:
            pass

    def _terminar_resize_input(self, _evento: tk.Event) -> None:
        self._resize_y = None

    def show_approval(self, text: str, on_approve: Callable, on_reject: Callable) -> None:
        self.aprobacion_texto.set(text)
        self.boton_aprobar.config(command=on_approve)
        self.boton_rechazar.config(command=on_reject)
        self.barra_aprobacion.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0), before=self.estado_label)
        self.boton_aprobar.focus_set()

    def hide_approval(self) -> None:
        if self.barra_aprobacion.winfo_ismapped():
            self.barra_aprobacion.pack_forget()
