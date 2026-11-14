"""Ciclo de autosave del editor y métricas del documento activo.

Extraído de `TukulApp` (DF-001, ADR-0005 paso 3). Dos responsabilidades que no
tienen que ver con el resto de la interfaz:

- el **respaldo de recuperación**: escribir lo editado en `autosave` cada pocos
  segundos mientras el documento siga sucio, rearmando el temporizador;
- las **métricas del pie**: palabras totales, palabras de la selección y tiempo
  de lectura estimado.

`EditorSession` es dueño de ambos temporizadores (`autosave_after`,
`stats_after`) y lee el editor a través del host. El host aporta `after` /
`after_cancel` (bucle de eventos), `editor` y `editor_stats` (lectura y
pintado), `session` (suciedad y ruta) y `closing` (parada ordenada). `TukulApp`
conserva sus métodos históricos como delegaciones y expone los temporizadores
como *properties* de compatibilidad.
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING, Any, Protocol

from tukul_core.autosave import clear_autosave, write_autosave

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones
    from collections.abc import Callable

#: Intervalo del respaldo de recuperación: se escribe solo si hay cambios.
AUTOSAVE_INTERVAL_MS = 5000
#: Retardo del recálculo de métricas tras una edición o un cambio de selección.
STATS_INTERVAL_MS = 300
#: Palabras por minuto usadas para estimar el tiempo de lectura.
PALABRAS_POR_MINUTO = 220


class _HostEditor(Protocol):
    """Contrato mínimo que `EditorSession` necesita del host."""

    @property
    def session(self) -> Any: ...

    @property
    def closing(self) -> bool: ...

    @property
    def editor_stats(self) -> Any: ...

    @property
    def editor(self) -> Any: ...

    def after(self, ms: int, func: Callable[[], object]) -> str: ...

    def after_cancel(self, id: str) -> None: ...


class EditorSession:
    """Autosave del editor y métricas del pie, con sus propios temporizadores."""

    def __init__(self, host: _HostEditor) -> None:
        self._host = host
        self.autosave_after: str | None = None
        self.stats_after: str | None = None

    # ─── Autosave ───────────────────────────────────────────────────────────

    def schedule_autosave(self) -> None:
        """Programa (o rearma) el respaldo de recuperación tras una edición."""
        if self.autosave_after is not None:
            self._host.after_cancel(self.autosave_after)
        self.autosave_after = self._host.after(AUTOSAVE_INTERVAL_MS, self.write_autosave)

    def write_autosave(self) -> None:
        """Vuelca el editor al respaldo si sigue sucio; se rearma si hay que insistir."""
        self.autosave_after = None
        if self._host.closing:
            return
        session = self._host.session
        if session.dirty and session.document_path is not None:
            try:
                write_autosave(session.document_path, self._host.editor.get("1.0", "end-1c"))
            except tk.TclError:
                return  # Ventana destruida mientras se volcaba.
            self.schedule_autosave()

    def clear_current_autosave(self) -> None:
        """Borra el respaldo del documento actual y detiene el temporizador."""
        ruta = self._host.session.document_path
        if ruta is not None:
            clear_autosave(ruta)
        if self.autosave_after is not None:
            self._host.after_cancel(self.autosave_after)
            self.autosave_after = None

    def cancelar_temporizadores(self) -> None:
        """Cancela los `after` pendientes (autosave y métricas) al cerrar.

        Sin esto, los temporizadores ya programados disparaban tras el cierre
        contra una Tcl destruida, dejando ruido «invalid command name».
        """
        for ident in (self.autosave_after, self.stats_after):
            if ident is not None:
                try:
                    self._host.after_cancel(ident)
                except tk.TclError:
                    pass
        self.autosave_after = None
        self.stats_after = None

    # ─── Métricas ───────────────────────────────────────────────────────────

    def schedule_stats(self) -> None:
        """Reprograma la actualización de métricas del pie."""
        if self.stats_after is not None:
            self._host.after_cancel(self.stats_after)
        self.stats_after = self._host.after(STATS_INTERVAL_MS, self.update_stats)

    def update_stats(self) -> None:
        """Reescribe las métricas del pie: palabras y tiempo de lectura."""
        self.stats_after = None
        editor = self._host.editor
        total = len(editor.get("1.0", "end-1c").split())
        seleccion = (editor.get("sel.first", "sel.last").strip()
                     if editor.tag_ranges("sel") else "")
        palabras_sel = len(seleccion.split()) if seleccion else 0
        if total:
            lectura = max(1, round(total / PALABRAS_POR_MINUTO))
            if palabras_sel:
                texto = f"{palabras_sel} de {total:,} palabras · {lectura} min de lectura"
            else:
                texto = f"{total:,} palabras · {lectura} min de lectura"
        else:
            texto = "0 palabras · 0 min de lectura"
        self._host.editor_stats.config(text=texto)
