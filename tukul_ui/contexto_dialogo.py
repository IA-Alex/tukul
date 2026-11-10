"""Diálogo de contexto de artículos y fuente de amenazas (CVE).

Concentra lo que antes vivía disperso en `TukulApp`:

- el diálogo «Contexto de artículos» (añadir/quitar referencias, añadir el
  artículo activo, disparar el fetch de CVEs y las ideas);
- la fuente de amenazas: consulta NVD/EPSS/KEV en un hilo daemon y publica el
  resultado al hilo de Tk;
- los mutadores del conjunto de contexto (upsert, autorización, botón).

La ventana se recibe por inyección (`ContextHost`), nunca se importa ni se
hereda: así se prueba con un doble y no hay ciclo `app -> contexto_dialogo ->
app`. Las operaciones sobre el contexto se delegan al host (`host._upsert_
context_article`, etc.) para que siga siendo la ventana la dueña de su estado.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Protocol, cast

from tukul_core.threat_feed import ThreatFeedError, build_threat_context
from tukul_ui import estilo as es
from tukul_ui.contexto import ContextArticle
from tukul_ui.worker_threads import WorkerThreads

logger = logging.getLogger("tukul")


class ContextHost(Protocol):
    """Lo que el controlador de contexto necesita de la ventana que lo aloja.

    Se mantiene estrecho a propósito: solo los miembros que este módulo usa.
    Los mutadores del contexto se llaman *en el host* para que la ventana
    siga siendo la dueña de su estado (y para conservar la API histórica).
    """

    closing: bool
    status: Any
    references_button: Any
    editor: Any
    context_articles: list[ContextArticle]

    @property
    def profile(self) -> Any: ...

    @property
    def session(self) -> Any: ...

    def after(self, ms: Any, func: Any, *args: Any) -> str: ...

    def winfo_screenwidth(self) -> int: ...

    def winfo_screenheight(self) -> int: ...

    def _registrar_reaplicar_tema(self, ancla: tk.Misc, reaplicar: Callable[[], None]) -> None: ...

    def _upsert_context_article(self, article: ContextArticle) -> bool: ...

    def _authorize_context_articles(self) -> None: ...

    def _update_references_button(self) -> None: ...

    def _add_current_article_to_context(self) -> bool: ...

    def _fetch_impact_suggestion(self, dialog: tk.Toplevel,
                                 on_done: Callable[[], None]) -> None: ...


def _en_el_hilo_de_tk() -> bool:
    """True si el llamador es el hilo que puede tocar Tcl (ver `ideas.py`)."""
    return threading.current_thread() is threading.main_thread()


class ContextController:
    """Diálogo de contexto y fetch de amenazas, con la ventana inyectada."""

    def __init__(self, host: ContextHost, *, threat_feed_hours: int,
                 threat_feed_source_id: str, max_indexed_file_bytes: int) -> None:
        self._host = host
        self._threat_feed_hours = threat_feed_hours
        self._threat_feed_source_id = threat_feed_source_id
        self._max_indexed_file_bytes = max_indexed_file_bytes

    # ─── Mutadores del conjunto de contexto ─────────────────────────────────

    def update_references_button(self) -> None:
        """Contexto: solo el número; las palabras se añaden cuando hay algo."""
        host = self._host
        count = len(host.context_articles)
        if count == 0:
            texto = "Contexto: 0"
        else:
            label = "artículo" if count == 1 else "artículos"
            texto = f"Contexto: {count} {label}"
        host.references_button.config(text=texto)

    def add_current_article_to_context(self) -> bool:
        """Guarda el texto visible como contexto antes de abrir o editar otro."""
        host = self._host
        content = host.editor.get("1.0", "end-1c")
        if not content.strip():
            return False
        path = host.session.document_path
        label = path.name if path else "Artículo sin guardar"
        source_id = f"article:{path.resolve()}" if path else "article:sin-ruta"
        return host._upsert_context_article(ContextArticle(source_id, label, content))

    def add_references(self, paths: tuple[str, ...] | list[str]) -> int:
        """Añade instantáneas de archivos de contexto sin alterar el editor."""
        host = self._host
        added = 0
        for raw_path in paths:
            try:
                path = Path(raw_path).resolve()
            except OSError:
                continue
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
                continue
            try:
                with path.open("rb") as source:
                    content = source.read(self._max_indexed_file_bytes).decode(
                        "utf-8", errors="replace")
            except OSError:
                continue
            if host._upsert_context_article(ContextArticle(f"article:{path}", path.name, content)):
                added += 1
        return added

    def ask_to_authorize_articles(self, labels: list[str], parent) -> bool:
        """La autorización ocurre al añadir contexto, nunca al enviar después."""
        if not labels:
            return False
        return messagebox.askyesno(
            "Autorizar artículos de contexto",
            "Se conservarán y podrán enviarse a "
            f"{self._host.profile.provider}/{self._host.profile.model} durante esta sesión:\n\n"
            + ", ".join(labels),
            parent=parent,
        )

    # ─── Fuente de amenazas (CVE) ───────────────────────────────────────────

    def fetch_threat_feed(self, dialog: tk.Toplevel, on_done: Callable[[], None]) -> None:
        """Consulta NVD/EPSS/KEV en segundo plano y añade el resultado como contexto.

        La red la inicia Tukul (no el proveedor LLM), por eso el disparo es
        una acción de UI explícita y nunca automático: ver `docs/SECURITY.md`.
        `build_threat_context` degrada por fuente y solo lanza si fallan las tres.
        El paquete resultante entra como una instantánea de contexto más y pasa
        por `ContextApprovalCache` antes de llegar a cualquier prompt.
        """
        host = self._host
        if not messagebox.askyesno(
            "Añadir CVEs recientes al contexto",
            "Tukul consultará ahora tres fuentes públicas de vulnerabilidades "
            "(NVD, EPSS de FIRST.org y el catálogo CISA KEV) para construir un "
            f"resumen de los CVE de las últimas {self._threat_feed_hours} h.\n\n"
            "Es una conexión saliente iniciada por la aplicación. El resultado se "
            "trata como contexto no confiable y se autoriza como cualquier otro "
            "artículo de contexto.\n\n¿Continuar?",
            parent=dialog,
        ):
            return
        host.status.set("Consultando fuentes de amenazas (CVE)…")

        def work() -> None:
            """Ejecuta el fetch HTTP fuera del hilo de Tk y devuelve el control por `after`."""
            detail: str | None = None
            try:
                packet, files = build_threat_context(hours=self._threat_feed_hours)
            except ThreatFeedError as error:
                detail = str(error)
            except Exception as error:
                # El hilo daemon no debe morir en silencio: se registra y se
                # reporta como fallo del fetch, igual que un ThreatFeedError.
                logger.error("Fallo inesperado en la fuente de amenazas: %s", error, exc_info=True)
                detail = str(error)
            if host.closing:
                return  # La ventana ya se está destruyendo: no tocar Tcl.
            if detail is not None:
                message = detail
                host.after(0, lambda: self.on_threat_feed_error(dialog, message))
                return
            host.after(0, lambda: self.on_threat_feed_ready(packet, files, on_done))

        WorkerThreads.start(work)

    def on_threat_feed_error(self, dialog: tk.Toplevel, detail: str) -> None:
        """Informa del fallo del fetch sin tumbar el diálogo de contexto."""
        self._host.status.set("No se pudo obtener el contexto de amenazas.")
        if dialog.winfo_exists():
            messagebox.showerror(
                "Fuente de amenazas no disponible",
                f"No se pudo construir el contexto de CVE:\n\n{detail}",
                parent=dialog,
            )

    def on_threat_feed_ready(
        self, packet: str, files: list[str], on_done: Callable[[], None]
    ) -> None:
        """Añade el paquete de amenazas como instantánea de contexto ya autorizada."""
        host = self._host
        label = f"CVEs recientes ({', '.join(files)})" if files else "CVEs recientes"
        host._upsert_context_article(
            ContextArticle(self._threat_feed_source_id, label, packet))
        host._authorize_context_articles()
        host.status.set("Contexto de CVEs recientes añadido y autorizado.")
        on_done()

    # ─── Diálogo de contexto ────────────────────────────────────────────────

    def manage_references(self) -> None:
        """Permite conservar artículos previos al cambiar el artículo activo."""
        host = self._host
        raiz = cast("tk.Tk", host)
        dialog = tk.Toplevel(raiz)
        dialog.title("Contexto de artículos")
        dialog.transient(raiz)
        dialog.configure(bg=es.SUPERFICIE)
        dialog.minsize(460, 280)
        dialog.geometry(es.tamano_ventana(580, 360, host.winfo_screenwidth(),
                                          host.winfo_screenheight(), minimo=(460, 280)))
        frame = ttk.Frame(dialog, style="Superficie.TFrame", padding=es.ESP["lg"])
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Artículos de contexto", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(frame, text=("El artículo de la izquierda es el activo. Añade aquí artículos previos (.md o .txt) "
                               "o un resumen de CVEs recientes: se conservan al abrir otro artículo y se autorizan al añadirlos. "
                               "«Añadir CVEs recientes» abre una conexión saliente a NVD/EPSS/CISA KEV."),
                  style="TenueSuperficie.TLabel", wraplength=520, justify="left").pack(
                      anchor="w", pady=(es.ESP["xs"], es.ESP["sm"]))
        # La fila de acciones se reserva ANTES de la lista expansible: con pack,
        # lo colocado después es lo que se recorta al estrechar la ventana.
        actions = ttk.Frame(frame, style="Superficie.TFrame")
        actions.pack(side="bottom", fill="x", pady=(es.ESP["lg"], 0))
        entries = tk.Listbox(frame, selectmode="extended", exportselection=False,
                             background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                             selectbackground=es.SELECCION, selectforeground=es.TEXTO,
                             relief="flat", highlightthickness=1,
                             highlightbackground=es.BORDE_CONTROL, highlightcolor=es.FOCO,
                             borderwidth=0, font=es.fuente(), activestyle="none")
        entries.pack(fill="both", expand=True)

        def refresh() -> None:
            """Recarga la lista de artículos de contexto desde la sesión."""
            entries.delete(0, "end")
            for article in host.context_articles:
                entries.insert("end", article.label)

        def add() -> None:
            """Añade artículos de contexto elegidos por el usuario, con autorización."""
            paths = filedialog.askopenfilenames(
                parent=dialog, title="Añadir artículos al contexto",
                filetypes=[("Artículos", "*.md *.txt"), ("Todos los archivos", "*.*")],
            )
            # Tk declara una cadena vacía al cancelar, aunque normalmente devuelve
            # una tupla. No iterar esa cadena evita tratar cada carácter como ruta.
            selected_paths = paths if isinstance(paths, tuple) else ()
            labels = [Path(path).name for path in selected_paths]
            if not self.ask_to_authorize_articles(labels, dialog):
                return
            count = self.add_references(selected_paths)
            host._authorize_context_articles()
            refresh()
            if count:
                host.status.set(f"{count} artículo(s) añadido(s) al contexto.")

        def remove() -> None:
            """Elimina los artículos de contexto seleccionados en la lista."""
            selected = list(entries.curselection())
            if not selected:
                return
            host.context_articles = [article for index, article in enumerate(host.context_articles)
                                     if index not in selected]
            host._update_references_button()
            refresh()
            host.status.set("Contexto de artículos actualizado.")

        # Acción primaria a la derecha, como en el resto de diálogos.
        def add_current() -> None:
            """Añade el artículo activo como contexto."""
            path = host.session.document_path
            label = path.name if path else "Artículo sin guardar"
            if not self.ask_to_authorize_articles([label], dialog):
                return
            added = host._add_current_article_to_context()
            host._authorize_context_articles()
            refresh()
            host.status.set("Artículo activo añadido al contexto." if added
                            else "Artículo activo actualizado en el contexto.")

        ttk.Button(actions, text="Añadir artículos…", style="Primaria.TButton",
                   command=add).pack(side="right")
        ttk.Button(actions, text="Quitar seleccionadas", command=remove).pack(
            side="right", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Añadir artículo activo", command=add_current).pack(
            side="left", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Añadir CVEs recientes…",
                   command=lambda: self.fetch_threat_feed(dialog, refresh)).pack(
            side="left", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Generar sugerencia de impacto…",
                   command=lambda: host._fetch_impact_suggestion(dialog, refresh)).pack(
            side="left", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="left")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        refresh()
        host._registrar_reaplicar_tema(
            dialog, lambda: self.reaplicar_tema_contexto(dialog, entries))
        entries.focus_set()

    def reaplicar_tema_contexto(self, dialog: tk.Toplevel, entries: tk.Listbox) -> None:
        """Repinta el diálogo de contexto al cambiar de tema, sin perder la lista."""
        dialog.configure(bg=es.SUPERFICIE)
        entries.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                          selectbackground=es.SELECCION, selectforeground=es.TEXTO,
                          highlightbackground=es.BORDE_CONTROL, highlightcolor=es.FOCO)
