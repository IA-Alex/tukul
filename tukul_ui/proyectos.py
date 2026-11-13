"""Flujos de proyecto: guardar y abrir artículo + conversación en un JSON.

Origen: H2 (`docs/audit/hallazgos-abiertos-2026-11-04.md`). Estos cuatro flujos
vivían en `TukulApp` y solo tocaban una parte estrecha de la ventana: diálogos de
archivo, la sesión del `DocumentManager`, el ámbito de documento y tres ayudantes
de interfaz. Separarlos deja la ventana con lo que es suyo (widgets y ciclo de
petición) y el flujo de proyecto con lo que es suyo.

La lógica de disco se queda en `DocumentManager`; este módulo es la capa de
interacción: pregunta, delega, informa y deja la ventana en un estado coherente.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Protocol

from tukul_core.autosave import read_autosave
from tukul_core.logging_config import setup_logging
from tukul_core.models import ArticleSession
from tukul_ui.document_manager import DocumentManager
from tukul_ui.document_scope import DocumentScope

# Mismo logger que el resto de la aplicación: `--health` y el log rotativo leen
# por este nombre, así que un logger suelto perdería el error en producción.
logger = setup_logging()


class VentanaDeProyectos(Protocol):
    """Lo que `TukulApp` ofrece al flujo de proyectos.

    Se declara como protocolo para que el contrato sea explícito y verificable:
    cualquier método nuevo que el flujo necesite de la ventana aparece aquí.
    """

    @property
    def session(self) -> ArticleSession: ...

    docs: DocumentManager
    scope: DocumentScope
    status: tk.StringVar

    def save_document(self, save_as: bool = False) -> bool: ...

    def _cancel_active_request(self) -> None: ...

    def _replace_editor_text(self, content: str) -> None: ...

    def _clear_history_widget(self) -> None: ...

    def append(self, who: str, text: str, es_respuesta: bool = True) -> None: ...

    def _close_review_dialogs(self) -> None: ...

    def _sincronizar_estado_sync(self, estado: str) -> None: ...

    def _mostrar_documento_activo(self) -> None: ...

    def update_context(self) -> None: ...

    def schedule_stats(self) -> None: ...


def save_project(ventana: VentanaDeProyectos) -> None:
    """Guarda el proyecto recuperable (artículo + conversación) en un JSON."""
    session = ventana.session
    if session.dirty and not ventana.save_document():
        return
    if session.document_path is None:
        messagebox.showinfo("Falta el artículo", "Guarda primero el artículo Markdown.")
        return
    options: dict = {"defaultextension": ".tukul.json", "filetypes": [("Proyecto", "*.tukul.json")]}
    # El proyecto guarda rutas relativas: proponer la carpeta del artículo evita
    # la ruta imposible (el artículo debe quedar bajo la carpeta del proyecto).
    options["initialdir"] = str(session.document_path.parent)
    options["initialfile"] = f"{session.document_path.stem}.tukul.json"
    path = filedialog.asksaveasfilename(**options)
    if not path:
        return
    # Persistencia a través del DocumentManager: era el dueño declarado de esta
    # responsabilidad, pero la app llamaba a storage por su cuenta y mantenía
    # una segunda implementación del mismo flujo.
    success, error = ventana.docs.save_project(session, Path(path))
    if success:
        ventana.status.set("Proyecto guardado.")
    else:
        messagebox.showerror(
            "Error al guardar proyecto",
            f"No se pudo guardar el proyecto:\n{error}",
        )
        logger.error("Error guardando proyecto: %s", error)


def open_project(ventana: VentanaDeProyectos) -> None:
    """Abre un proyecto y restaura el artículo y su conversación."""
    session = ventana.session
    # Cancelar cualquier solicitud activa antes de cambiar de proyecto
    if session.request_active:
        if not messagebox.askyesno("Solicitud activa", "¿Cancelar la consulta en curso?"):
            return
        ventana._cancel_active_request()

    # Verificar cambios sin guardar antes de abrir otro proyecto
    if session.dirty and not messagebox.askyesno(
        "Cambios sin guardar", "¿Descartar cambios locales?"
    ):
        return
    path = filedialog.askopenfilename(filetypes=[("Proyecto Tukul", "*.tukul.json")])
    if not path:
        return
    # Carga a través del DocumentManager: el flujo estaba duplicado aquí y allí,
    # con manejo de errores divergente y la copia del manager sin usar ni probar.
    success, error, nueva = ventana.docs.open_project(Path(path))
    if not success:
        messagebox.showerror("Proyecto no válido", error)
        return
    # `DocumentManager.save_document` borra el autosave al guardar. Si el
    # artículo del proyecto ya no existe en disco, `open_project` lo rechaza;
    # pero si existe y tiene respaldo, la copia recuperable es la más reciente.
    respaldo = read_autosave(nueva.document_path) if nueva.document_path else None
    if respaldo is not None:
        nueva.article = respaldo
    ventana.docs.set_session(nueva)
    # El editor y el historial se rellenan con lo que ACABA de cargarse (`nueva`),
    # no con lo que había en pantalla: mezclar ambas sesiones mostraba el
    # artículo anterior, un defecto real que destapó `test_restaura_...`.
    ventana._replace_editor_text(nueva.article)
    ventana._clear_history_widget()
    for item in nueva.conversation:
        ventana.append("Tú" if item.role == "user" else "Tukul", item.content)
    enter_document_scope(ventana, nueva.document_path)
    nueva.dirty = False
    ventana._sincronizar_estado_sync("clean")
    ventana._mostrar_documento_activo()
    ventana.update_context()
    ventana.schedule_stats()
    ventana.status.set("Proyecto abierto.")


def enter_document_scope(ventana: VentanaDeProyectos, document_path: Path | None) -> None:
    """Entra en el ámbito de un documento reemplazando el anterior por completo.

    Sustituir el objeto en vez de limpiar campo a campo es lo que hace
    imposible olvidarse de uno: cualquier campo nuevo de DocumentScope se
    renueva aquí sin tocar este método.

    `approved_contexts` queda fuera a propósito: su clave es (endpoint,
    proveedor, archivos, huella del paquete), todo derivado del workspace y
    no del artículo abierto. Vaciarlo añadiría un modal por documento.
    """
    ventana._close_review_dialogs()
    ventana.scope = DocumentScope(document_path=document_path)
