"""Tooltip ligero para controles de Tk, sin dependencias externas.

Los símbolos de la barra (☰, ◧, ◨) no se explican solos: un tooltip da el
nombre de la acción y su atajo sin ensuciar la interfaz con texto permanente.
"""
from __future__ import annotations

import tkinter as tk

from articulador_ui import estilo as es


class ToolTip:
    """Muestra una pista al detener el cursor sobre un widget.

    Se instancia una vez por widget y se registra por sí solo en los eventos
    <Enter>/<Leave>. Solo hay un tooltip visible a la vez en toda la app.
    """

    _activo: ToolTip | None = None

    def __init__(self, widget: tk.Misc, texto: str, demora: int = 500) -> None:
        self.widget = widget
        self.texto = texto
        self.demora = demora
        self._id: str | None = None
        self._ventana: tk.Toplevel | None = None
        widget.bind("<Enter>", self._programar, add="+")
        widget.bind("<Leave>", self._ocultar, add="+")
        # Las pistas no deben depender exclusivamente del puntero: también
        # aparecen al llegar al control con Tab, útil para teclado y ayudas
        # tecnológicas que exponen el foco del widget.
        widget.bind("<FocusIn>", self._programar, add="+")
        widget.bind("<FocusOut>", self._ocultar, add="+")
        widget.bind("<ButtonPress>", self._ocultar, add="+")

    def _programar(self, _evento: tk.Event | None = None) -> None:
        self._cancelar()
        self._id = self.widget.after(self.demora, self._mostrar)

    def set_texto(self, texto: str) -> None:
        """Actualiza la pista (p. ej. al cambiar de tema) sin recrear el registro."""
        self.texto = texto
        if self._ventana is not None:
            try:
                for hijo in self._ventana.winfo_children():
                    if isinstance(hijo, tk.Label):
                        hijo.config(text=self.texto)
            except tk.TclError:
                pass

    def _mostrar(self) -> None:
        self._id = None
        if not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
            return
        if not self._ventana_es_de_la_ventana_activa():
            # Un diálogo modal (o cualquier Toplevel) tapa la ventana principal:
            # una pista de un control de fondo aparecería ENCIMA del diálogo y
            # daría a entender que ese control es el que tiene el foco.
            return
        ToolTip._ocultar_global()
        self._ventana = tk.Toplevel(self.widget)
        self._ventana.wm_overrideredirect(True)
        tk.Label(
            self._ventana,
            text=self.texto,
            background=es.SUPERFICIE_ALTA,
            foreground=es.TEXTO,
            relief="flat",
            borderwidth=0,
            padx=es.ESP["sm"],
            pady=es.ESP["xs"],
            font=es.fuente(es.TIPO_SM),
        ).pack()
        x = self.widget.winfo_rootx() + es.ESP["sm"]
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + es.ESP["xs"]
        self._ventana.wm_geometry(f"+{x}+{y}")
        ToolTip._activo = self

    def _ventana_es_de_la_ventana_activa(self) -> bool:
        """True si el widget pertenece a la ventana superior que tiene el foco.

        Se considera «activa» la ventana con grabbing a nivel de aplicación (un
        modal) y, si no hay ninguno, la que contiene el foco. Así el tooltip de
        un control de la ventana principal desaparece mientras hay un diálogo
        abierto encima.
        """
        try:
            activa = self.widget.winfo_toplevel().grab_current()
            if activa is None:
                activa = self.widget.winfo_toplevel().focus_get()
            if activa is None:
                return True
            return activa.winfo_toplevel() is self.widget.winfo_toplevel()
        except (AttributeError, tk.TclError):
            return True


    def _ocultar(self, _evento: tk.Event | None = None) -> None:
        self._cancelar()
        if self._ventana is not None:
            try:
                self._ventana.destroy()
            except tk.TclError:
                pass
            self._ventana = None
        if ToolTip._activo is self:
            ToolTip._activo = None

    def _cancelar(self) -> None:
        if self._id is not None:
            try:
                self.widget.after_cancel(self._id)
            except tk.TclError:
                pass
            self._id = None

    @classmethod
    def _ocultar_global(cls) -> None:
        if cls._activo is not None:
            cls._activo._ocultar()
