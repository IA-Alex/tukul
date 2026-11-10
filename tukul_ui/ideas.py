"""Generación y selección de ideas de artículo desde fuentes en tiempo real.

Este controlador concentra el pipeline que antes vivía disperso en `TukulApp`:

1. `FeedOrchestrator.fetch_all()` consulta las fuentes oficiales.
2. `CorrelationEngine.correlate()` cruza las entradas.
3. `IdeaGenerator.generate()` produce las ideas (reglas + LLM opcional).
4. Se muestra un diálogo para que la persona elija una, que se añade al
   contexto del artículo.

La ventana se recibe por inyección (`host`), no se hereda ni se importa: así el
módulo se prueba sin montar la app completa y no hay ciclo `app -> ideas ->
app`. Todo contacto con Tk desde el worker se publica al hilo de Tk, nunca se
toca Tcl desde fuera.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Protocol

from tukul_core.impact_analyzer import CorrelationEngine, IdeaGenerator
from tukul_core.real_time_feed import FeedOrchestrator
from tukul_ui import estilo as es
from tukul_ui.contexto import ContextArticle
from tukul_ui.worker_threads import WorkerThreads

if TYPE_CHECKING:
    from tukul_core.models import ArticleIdea, CorrelationGroup, FeedEntry, LlmProfile

logger = logging.getLogger("tukul")


class IdeasHost(Protocol):
    """Lo que el controlador de ideas necesita de la ventana que lo aloja.

    Es un contrato mínimo y explícito: solo los miembros que el pipeline usa.
    Mantenerlo estrecho es lo que permite probar el controlador sin la app.
    """

    closing: bool
    status: Any

    @property
    def profile(self) -> LlmProfile: ...

    @property
    def key(self) -> str: ...

    # Firma laxa a propósito: solo se usa `after(0, callback)`; así encaja con
    # la sobrecarga de `tkinter.Misc.after` sin pelearse con su tipado exacto.
    def after(self, ms: Any, func: Any, *args: Any) -> str: ...

    def winfo_screenwidth(self) -> int: ...

    def winfo_screenheight(self) -> int: ...

    def append(self, who: str, text: str, es_respuesta: bool = ...) -> None: ...

    def _upsert_context_article(self, article: ContextArticle) -> bool: ...

    def _authorize_context_articles(self) -> None: ...

    def _registrar_reaplicar_tema(self, ancla: tk.Misc, reaplicar: Callable[[], None]) -> None: ...


def _en_el_hilo_de_tk() -> bool:
    """True si el llamador es el hilo que puede tocar Tcl.

    `after()` desde un worker lanza `RuntimeError: main thread is not in main
    loop` en CPython 3.13, y ese error —surgido durante la recolección de
    basura— puede abortar el proceso entero en lugar de propagarse. Los
    workers son daemon: pueden sobrevivir al cierre y llegar aquí. Mejor no
    programar nada que morir.
    """
    import threading

    return threading.current_thread() is threading.main_thread()


class IdeasController:
    """Orquesta el pipeline de ideas y el diálogo de selección."""

    def __init__(self, host: IdeasHost, feed_cache_dir: Path, threat_feed_hours: int) -> None:
        self._host = host
        self._feed_cache_dir = feed_cache_dir
        self._threat_feed_hours = threat_feed_hours

    # ─── Entrada desde la UI ────────────────────────────────────────────────

    def fetch_suggestion(self, dialog: tk.Toplevel, on_done: Callable[[], None]) -> None:
        """Orquesta el pipeline de correlación e ideas en segundo plano.

        1. FeedOrchestrator.fetch_all() → obtiene datos de fuentes
        2. CorrelationEngine.correlate() → cruza entradas por CVE, tópicos, keywords
        3. IdeaGenerator.generate() → genera ideas de artículo desde correlaciones
        4. Muestra un diálogo con las ideas para que el usuario seleccione una.

        El LLM es opcional: si está configurado, enriquece las ideas. Si no,
        las ideas son completamente basadas en reglas.
        """
        host = self._host
        if not host.profile.enabled or not host.key:
            messagebox.showinfo(
                "LLM no configurado",
                "Configura un perfil LLM y una API key para generar sugerencias.",
                parent=dialog,
            )
            return

        if not messagebox.askyesno(
            "Generar ideas de artículo",
            "Tukul consultará fuentes oficiales (NVD, EPSS, KEV, MITRE ATT&CK, arXiv) "
            "y correlacionará las entradas para generar ideas de artículo. "
            "El resultado se mostrará para que selecciones la que quieras desarrollar.\n\n"
            "Es una conexión saliente iniciada por la aplicación. "
            "¿Continuar?",
            parent=dialog,
        ):
            return

        host.status.set("Generando ideas de artículo…")

        # Capturar perfil y key en el hilo de UI para evitar condiciones de carrera
        profile = host.profile
        api_key = host.key
        cache_path = self._feed_cache_dir / "feed_cache.json"

        def work() -> None:
            """Ejecuta el pipeline fuera del hilo de Tk y publica el resultado.

            No llama a `logging` desde aquí: aunque el módulo de log ya exista,
            formatear una excepción con `exc_info` durante una recolección de
            basura en curso puede abortar el intérprete en CPython 3.13. El
            detalle viaja al hilo de Tk, que lo registra con su contexto.
            """
            detalle: str | None = None
            try:
                # Al cerrar (o al destruir la ventana en las pruebas), cualquier
                # contacto con Tk desde aquí aborta el intérprete: el hilo
                # arranca tarde, ya sin interfaz, y no hay a quién responder.
                if host.closing:
                    return
                self._ejecutar_pipeline(
                    dialog, profile, api_key, cache_path, on_done)
            except RuntimeError as error:
                detalle = f"error de orquestación: {error}"
            except Exception as error:
                detalle = f"Error inesperado: {type(error).__name__}: {error}"
            if detalle is not None:
                self._registrar_error(dialog, detalle)

        WorkerThreads.start(work)

    # ─── Pipeline (hilo worker) ─────────────────────────────────────────────

    def _ejecutar_pipeline(self, dialog, profile, api_key, cache_path,
                           on_done: Callable[[], None]) -> bool:
        """Feed → correlación → ideas. Devuelve False si no hay nada que mostrar.

        Se ejecuta en el worker; cualquier callback de UI se programa con
        `after`, nunca se toca Tk desde aquí.
        """
        orchestrator = FeedOrchestrator(
            cache_path=cache_path,
            ttl_minutes=15,
            on_progress=lambda msg: logger.info("IdeaGeneration: %s", msg),
        )
        entries = orchestrator.fetch_all(hours=self._threat_feed_hours)
        if not entries:
            self._publicar_error(dialog, "No se obtuvieron entradas de las fuentes.")
            return False

        correlations = CorrelationEngine().correlate(entries)
        if not correlations:
            self._publicar_error(
                dialog, "No se encontraron correlaciones entre las fuentes.")
            return False

        ideas = IdeaGenerator(self._llm_de_ideas(profile, api_key)).generate(
            correlations, entries)
        if not ideas:
            self._publicar_error(
                dialog, "No se pudieron generar ideas a partir de las correlaciones.")
            return False

        host = self._host
        host.after(
            0,
            lambda: self.show_selection_dialog(
                dialog, ideas, entries, correlations, on_done),
        )
        return True

    @staticmethod
    def _llm_de_ideas(profile, api_key) -> Callable[[str], str] | None:
        """Callable del LLM para enriquecer ideas, o None sin credenciales."""
        if not (profile.enabled and api_key):
            return None
        from tukul_core.llm import LLMClient  # import diferido: solo si se usa

        def _llm_callable(prompt: str) -> str:
            return LLMClient().complete(profile, api_key, prompt).content
        return _llm_callable

    def _registrar_error(self, dialog, detalle: str) -> None:
        """Lleva un fallo del pipeline al hilo de Tk: log y aviso, sin tocar Tcl aquí.

        Se llama desde el worker. Registrar o programar `after()` desde ahí puede
        abortar el intérprete, así que el mensaje se publica tal cual y lo
        registra `on_error`, ya en el hilo de Tk.
        """
        self._publicar_error(dialog, detalle)

    def _publicar_error(self, dialog, mensaje: str) -> None:
        """Publica un error del pipeline en el hilo de Tk.

        Se llama desde el worker de ideas, que es daemon y puede llegar aquí
        cuando la ventana ya no existe. `after()` desde otro hilo aborta el
        proceso en CPython 3.13, así que fuera del hilo de Tk solo se registra.
        """
        if not _en_el_hilo_de_tk():
            logger.warning("IdeaGeneration: la interfaz ya no está disponible: %s", mensaje)
            return
        try:
            self._host.after(0, lambda: self._on_error(dialog, mensaje))
        except (RuntimeError, tk.TclError):
            logger.debug("Ventana destruida; error de ideas descartado")

    def _on_error(self, dialog: tk.Toplevel, detail: str) -> None:
        """Informa del fallo al generar la sugerencia."""
        logger.error("IdeaGeneration: %s", detail)
        self._host.status.set("No se pudo generar la sugerencia de impacto.")
        if dialog.winfo_exists():
            messagebox.showerror(
                "Sugerencia no disponible",
                f"No se pudo generar la sugerencia de impacto:\n\n{detail}",
                parent=dialog,
            )

    # ─── Diálogo de selección ───────────────────────────────────────────────

    def show_selection_dialog(
        self,
        parent_dialog: tk.Toplevel,
        ideas: list[ArticleIdea],
        all_entries: list[FeedEntry],
        correlations: list[CorrelationGroup],
        on_done: Callable[[], None],
    ) -> None:
        """Muestra un diálogo con las ideas generadas para que el usuario seleccione una.

        Al seleccionar una idea, se añade como ContextArticle con trazabilidad
        a las fuentes que la respaldan.
        """
        host = self._host
        dialog = tk.Toplevel(parent_dialog)
        dialog.title("Ideas de art\u00edculo generadas")
        dialog.transient(parent_dialog)
        dialog.configure(bg=es.SUPERFICIE)
        dialog.minsize(520, 340)
        dialog.geometry(es.tamano_ventana(640, 480, host.winfo_screenwidth(),
                                          host.winfo_screenheight(), minimo=(520, 340)))

        frame = ttk.Frame(dialog, style="Superficie.TFrame", padding=es.ESP["lg"])
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"Se generaron {len(ideas)} ideas a partir de las fuentes consultadas. "
                 "Selecciona una para desarrollarla como art\u00edculo.",
            style="TenueSuperficie.TLabel",
            wraplength=580,
            justify="left",
        ).pack(anchor="w", pady=(0, es.ESP["sm"]))

        list_frame = ttk.Frame(frame, style="Superficie.TFrame")
        list_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        idea_listbox = tk.Listbox(
            list_frame,
            selectmode="single",
            exportselection=False,
            background=es.SUPERFICIE_ALTA,
            foreground=es.TEXTO,
            selectbackground=es.SELECCION,
            selectforeground=es.TEXTO,
            relief="flat",
            highlightthickness=1,
            highlightbackground=es.BORDE_CONTROL,
            highlightcolor=es.FOCO,
            borderwidth=0,
            font=es.fuente(),
            activestyle="none",
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=idea_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        idea_listbox.pack(side="left", fill="both", expand=True)

        for idx, idea in enumerate(ideas, 1):
            urgency_icon = {
                "inmediata": "\U0001f534",
                "alta": "\U0001f7e0",
                "media": "\U0001f7e1",
                "baja": "\U0001f7e2",
            }.get(idea.urgency, "\u26aa")
            audience_label = {
                "directivos": "\U0001f454",
                "tecnicos": "\U0001f4bb",
                "publico general": "\U0001f465",
            }.get(idea.target_audience, "\U0001f464")
            confidence_pct = int(idea.confidence * 100)
            display = (
                f"{idx:2d}. [{urgency_icon}{audience_label}] "
                f"{idea.title[:80]} "
                f"({confidence_pct}% confianza)"
            )
            idea_listbox.insert("end", display)

        # Vista previa de la idea seleccionada
        preview_frame = ttk.Frame(frame, style="Superficie.TFrame")
        preview_frame.pack(fill="x", pady=(es.ESP["sm"], 0))

        preview_label = ttk.Label(
            preview_frame,
            text="Selecciona una idea para ver los detalles",
            style="TenueSuperficie.TLabel",
            wraplength=580,
            justify="left",
        )
        preview_label.pack(anchor="w")

        def on_select(_event: object = None) -> None:
            """Muestra la vista previa de la idea seleccionada."""
            selection = idea_listbox.curselection()
            if not selection:
                return
            idx = selection[0]
            idea = ideas[idx]
            corr = next(
                (c for c in correlations if c.id == idea.correlation_id),
                None,
            )
            sources_str = ", ".join(corr.sources) if corr else "\u2014"
            preview_label.config(
                text=(
                    f"T\u00edtulo: {idea.title}\n"
                    f"Audiencia: {idea.target_audience}  |  "
                    f"Urgencia: {idea.urgency}  |  "
                    f"Confianza: {int(idea.confidence * 100)}%\n"
                    f"Fuentes: {sources_str}\n\n"
                    f"\u00c1ngulo: {idea.angle[:200]}\n\n"
                    f"Razonamiento: {idea.reasoning[:200]}"
                )
            )

        idea_listbox.bind("<<ListboxSelect>>", on_select)

        # Botones de acci\u00f3n
        actions = ttk.Frame(frame, style="Superficie.TFrame")
        actions.pack(fill="x", pady=(es.ESP["lg"], 0))

        def accept_idea() -> None:
            """A\u00f1ade la idea seleccionada como ContextArticle y cierra el di\u00e1logo."""
            selection = idea_listbox.curselection()
            if not selection:
                messagebox.showinfo(
                    "Seleccionar idea",
                    "Selecciona una idea de la lista antes de continuar.",
                    parent=dialog,
                )
                return
            idx = selection[0]
            idea = ideas[idx]

            corr = next(
                (c for c in correlations if c.id == idea.correlation_id),
                None,
            )
            sources_detail = ""
            if corr:
                sources_detail = (
                    f"\n\n**Correlaci\u00f3n:** {corr.summary}\n"
                    f"**Relevancia:** {corr.relevance_score}\n"
                    f"**Fuentes:** {', '.join(corr.sources)}"
                )

            content = (
                f"## Idea: {idea.title}\n\n"
                f"**Audiencia:** {idea.target_audience}  |  "
                f"**Urgencia:** {idea.urgency}  |  "
                f"**Confianza:** {int(idea.confidence * 100)}%\n\n"
                f"### \u00c1ngulo narrativo\n{idea.angle}\n\n"
                f"### Por qu\u00e9 ahora\n{idea.reasoning}"
                f"{sources_detail}"
            )

            article = ContextArticle(
                source_id=idea.id,
                label=f"Idea: {idea.title[:50]}",
                content=content,
            )
            host._upsert_context_article(article)
            host._authorize_context_articles()
            host.append("Tukul", content, es_respuesta=False)
            host.status.set(f"Idea seleccionada: {idea.title}")
            dialog.destroy()
            on_done()

        ttk.Button(
            actions, text="Desarrollar esta idea",
            style="Primaria.TButton", command=accept_idea
        ).pack(side="right")
        ttk.Button(
            actions, text="Cancelar",
            command=dialog.destroy,
        ).pack(side="right", padx=(0, es.ESP["sm"]))

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Return>", lambda _event: accept_idea())
        idea_listbox.focus_set()

        host._registrar_reaplicar_tema(
            dialog,
            lambda: self._reaplicar_tema(dialog, idea_listbox, preview_label),
        )

    def _reaplicar_tema(
        self, dialog: tk.Toplevel, idea_listbox: tk.Listbox, preview: ttk.Label
    ) -> None:
        """Repinta el di\u00e1logo de ideas al cambiar de tema."""
        dialog.configure(bg=es.SUPERFICIE)
        idea_listbox.configure(
            background=es.SUPERFICIE_ALTA,
            foreground=es.TEXTO,
            selectbackground=es.SELECCION,
            selectforeground=es.TEXTO,
            highlightbackground=es.BORDE_CONTROL,
            highlightcolor=es.FOCO,
        )
