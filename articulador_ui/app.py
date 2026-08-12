from __future__ import annotations

import hashlib
import os
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import TypeAlias

from articulador_core import storage
from articulador_core.config_validator import validate_startup_config
from articulador_core.context import (
    MAX_CONTEXT_EXCERPT_CHARS,
    MAX_CONTEXT_PACKET_CHARS,
    MAX_INDEXED_FILE_BYTES,
)
from articulador_core.llm import SYSTEM_PROMPT, estimate_prompt_tokens
from articulador_core.logging_config import setup_logging
from articulador_core.models import ArticleSession, ChatMessage, LlmProfile
from articulador_core.prompting import build_editor_prompt
from articulador_core.review import parse_findings
from articulador_ui import estilo as es
from articulador_ui.chunk_buffer import ChunkBuffer
from articulador_ui.context_orchestrator import ContextOrchestrator
from articulador_ui.dialogs import show_context_dialog, show_review_dialog, show_settings_dialog
from articulador_ui.document_manager import DocumentManager
from articulador_ui.document_scope import DocumentScope
from articulador_ui.estado import ESTADOS_ACTIVOS, EstadoUI
from articulador_ui.llm_session_manager import LLMSessionManager

ContextApprovalKey: TypeAlias = tuple[str, str, tuple[str, ...], str]

# Compatibilidad para los diálogos, que leen app.COLORS. El sistema visual vive
# en articulador_ui/estilo.py y es la fuente única.
COLORS = {"bg": es.FONDO, "panel": es.SUPERFICIE, "raised": es.SUPERFICIE_ALTA,
          "field": es.SUPERFICIE_ALTA, "text": es.TEXTO, "muted": es.TEXTO_TENUE,
          "muted_light": es.TEXTO_TENUE, "accent": es.ACENTO,
          "accent_text": es.ACENTO_TEXTO, "border": es.BORDE,
          "selection": es.SELECCION, "assistant": es.VOZ_ASISTENTE}
REVIEW_PROMPT = (
    'Revisa el artículo y responde SOLO JSON válido: '
    '{"findings":[{"category":"ortografía|gramática|semántica|redundancia|estructura",'
    '"severity":"alta|media|baja","original":"fragmento exacto","suggestion":"reemplazo",'
    '"reason":"breve"}]}. Máximo 12 hallazgos. No inventes fragmentos.'
)
logger = setup_logging()


class ArticuladorApp(tk.Tk):
    def __init__(self, config_path: Path = storage.CONFIG_PATH, workspace_root: Path | None = None) -> None:
        super().__init__()
        # UI config
        self.COLORS = COLORS
        self.title("Articulador")
        # El tamaño se calcula UNA vez, aquí y de forma síncrona. Antes se fijaba
        # un valor y 100 ms después un `after` lo sobrescribía, pisando también
        # cualquier geometría que el usuario o quien integra la app hubiera
        # establecido entretanto.
        self._aplicar_tamano_inicial()

        # LLM profiles
        self.config_path = config_path
        self.profiles, self.active_profile = storage.load_profiles(config_path)
        # Auditoría de arranque: deja en el log por qué un perfil no responderá,
        # sin interrumpir con diálogos al abrir.
        validate_startup_config(self.profiles, self.active_profile)
        self.session_keys: dict[str, str] = {}
        self._session_keys_max = 32

        # Managers (refactorización de responsabilidades)
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.docs = DocumentManager()
        self.context = ContextOrchestrator(self.workspace_root)
        self.llm = LLMSessionManager()

        # Session & UI state (referencia dinámica a través de property)
        # dict-como-conjunto-ordenado: permite desalojo FIFO real (ver confirm_and_send).
        self.approved_contexts: dict[ContextApprovalKey, None] = {}
        # Todo el estado derivado del documento vive en un único objeto que se
        # reemplaza entero al cambiar de artículo (ver DocumentScope).
        self.scope = DocumentScope()
        # Referencias elegidas de forma explícita. No pertenecen al documento
        # activo ni se descubren recorriendo el workspace: permanecen durante
        # esta sesión hasta que la persona las quite.
        self.reference_files: list[Path] = []
        self.review_dialogs: list[tk.Toplevel] = []
        self.stats_after = None
        self.report_callback_exception = self.handle_callback_error
        self.cancel_event: threading.Event | None = None
        self.streaming_request: int | None = None
        self.streaming_text = ""
        self.closing = False
        # Tk encola <<Modified>> de forma asíncrona: sin esta bandera, el documento
        # recién abierto se marcaba como "Cambios sin guardar" en el ciclo siguiente.
        self._suppress_modified = False

        # Contador de generación global (nunca reinicia) para prevenir contaminación de respuestas
        self.generation_counter = 0
        # Tipos de solicitud asociados a cada request_id
        self.request_types: dict[int, str] = {}  # request_id -> "normal"|"review"
        # Dos canales worker → UI, con garantías distintas a propósito:
        #  - control: SIN tope y con put_nowait. Un complete/error jamás debe
        #    perderse ni bloquear al worker detrás de una ráfaga de texto.
        #  - chunks: acumulador con lock, no bloqueante y coalescible.
        # Compartir una sola cola limitada hacía que una ráfaga pudiera dejar la
        # finalización de la petición esperando con la conexión abierta.
        self.control_queue: queue.Queue = queue.Queue()
        self.chunks = ChunkBuffer()

        self._theme()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)

    @property
    def session(self) -> ArticleSession:
        """Referencia dinámica a sesión actual (siempre sincronizada con DocumentManager)."""
        return self.docs.session

    @property
    def profile(self) -> LlmProfile: return self.profiles[self.active_profile]
    @property
    def key(self) -> str: return os.environ.get(self.profile.api_key_env) or self.session_keys.get(self.active_profile, "") or storage.load_key(self.active_profile)

    def _add_session_key(self, profile: str, key: str) -> None:
        """Agrega o actualiza una key de sesión con desalojo LRU real.

        Actualizar un perfil ya presente no hace crecer el diccionario, así que no
        debe desalojar a nadie: antes, reconfigurar un perfil borraba la key de otro.
        """
        already_known = profile in self.session_keys
        if already_known:
            self.session_keys.pop(profile)  # Reinsertar lo mueve al final (más reciente).
        elif len(self.session_keys) >= self._session_keys_max:
            self.session_keys.pop(next(iter(self.session_keys)), None)
        self.session_keys[profile] = key

    def _aplicar_tamano_inicial(self) -> None:
        """Propone un tamaño inicial acorde a la pantalla. Se aplica una sola vez.

        Cualquier `geometry()` posterior —del usuario, de una restauración de
        sesión o de quien integre la aplicación— manda, porque aquí no hay
        ninguna reprogramación que lo pise después.
        """
        ancho_pantalla = self.winfo_screenwidth()
        alto_pantalla = self.winfo_screenheight()
        if ancho_pantalla > 100 and alto_pantalla > 100:
            ancho = min(int(ancho_pantalla * 0.8), 1400)
            alto = min(int(alto_pantalla * 0.8), 900)
            self.minsize(min(720, ancho), min(540, alto))
            self.geometry(f"{ancho}x{alto}")
        else:
            self.minsize(720, 540)
            self.geometry("1180x760")

    def _theme(self) -> None:
        """Aplica el sistema visual: un fondo, dos superficies, un acento."""
        self.configure(bg=es.FONDO)
        style = ttk.Style(self)
        try: style.theme_use("clam")
        except tk.TclError: pass

        style.configure(".", background=es.FONDO, foreground=es.TEXTO, font=es.fuente(),
                        focuscolor=es.FOCO)
        style.configure("TFrame", background=es.FONDO)
        style.configure("Cabecera.TFrame", background=es.SUPERFICIE_ALTA)
        style.configure("Superficie.TFrame", background=es.SUPERFICIE)
        style.configure("Alta.TFrame", background=es.SUPERFICIE_ALTA)
        style.configure("TLabel", background=es.FONDO, foreground=es.TEXTO)
        style.configure("Superficie.TLabel", background=es.SUPERFICIE, foreground=es.TEXTO)
        style.configure("Tenue.TLabel", background=es.FONDO, foreground=es.TEXTO_TENUE,
                        font=es.fuente(es.TIPO_SM))
        style.configure("TenueSuperficie.TLabel", background=es.SUPERFICIE,
                        foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM))
        style.configure("Titulo.TLabel", background=es.SUPERFICIE, foreground=es.TEXTO,
                        font=es.fuente(negrita=True))
        # Franja inferior: continua, tenue y de una sola pieza.
        style.configure("Cabecera.TLabel", background=es.SUPERFICIE_ALTA,
                        foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM))
        style.configure("Pie.TFrame", background=es.SUPERFICIE)
        style.configure("Pie.TLabel", background=es.SUPERFICIE, foreground=es.TEXTO_TENUE,
                        font=es.fuente(es.TIPO_SM))
        # El divisor es una señal de ajuste, no un borde de panel dominante.
        # `sashthickness` fija la zona sensible al arrastre: por debajo de 4 px
        # el agarre se vuelve incómodo, así que se mantiene fino pero usable.
        style.configure("TPanedwindow", background=es.BORDE)
        style.configure("Sash", background=es.BORDE, bordercolor=es.BORDE,
                        sashthickness=4, gripcount=0, lightcolor=es.BORDE,
                        darkcolor=es.BORDE)
        # Paneles sin marco: la separación la dan la superficie y el divisor.
        style.configure("TLabelframe", background=es.SUPERFICIE,
                        bordercolor=es.SUPERFICIE, relief="flat", borderwidth=0)
        style.configure("TLabelframe.Label", background=es.SUPERFICIE,
                        foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM, negrita=True))

        # Estados unificados de los controles. Cuatro señales, siempre las mismas:
        #   reposo  -> superficie elevada
        #   hover   -> un escalón más claro (borde)
        #   pulsado -> vuelve a la superficie base, con el borde en foco
        #   inhabilitado -> fondo hundido Y texto tenue (no solo color: el
        #                   contraste baja, y ttk además ignora el clic)
        estados_fondo = [("disabled", es.SUPERFICIE), ("pressed", es.SUPERFICIE),
                         ("active", es.BORDE)]
        estados_texto = [("disabled", es.TEXTO_TENUE)]
        estados_borde = [("focus", es.FOCO), ("pressed", es.FOCO),
                         ("disabled", es.SUPERFICIE)]
        style.configure("TButton", background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                        bordercolor=es.BORDE, focuscolor=es.FOCO, relief="flat",
                        padding=(es.ESP["sm"], es.ESP["xs"] + 1))
        style.map("TButton", background=estados_fondo, foreground=estados_texto,
                  bordercolor=estados_borde)
        style.configure("Primaria.TButton", background=es.ACENTO, foreground=es.ACENTO_TEXTO,
                        bordercolor=es.ACENTO, focuscolor=es.ACENTO_TEXTO, relief="flat",
                        font=es.fuente(negrita=True), padding=(es.ESP["md"], es.ESP["xs"] + 2))
        style.map("Primaria.TButton",
                  background=[("disabled", es.SUPERFICIE_ALTA), ("pressed", es.ACENTO),
                              ("active", es.ACENTO_ACTIVO)],
                  foreground=[("disabled", es.TEXTO_TENUE)],
                  bordercolor=[("focus", es.FOCO), ("disabled", es.SUPERFICIE_ALTA)])
        style.configure("Guardar.TButton", background=es.SUPERFICIE_ALTA,
                        foreground=es.TEXTO, bordercolor=es.BORDE, relief="flat",
                        focuscolor=es.FOCO, font=es.fuente(negrita=True),
                        padding=(es.ESP["sm"], es.ESP["xs"] + 1))
        style.map("Guardar.TButton", background=estados_fondo, foreground=estados_texto,
                  bordercolor=estados_borde)
        style.configure("Plana.TButton", background=es.SUPERFICIE, foreground=es.TEXTO_TENUE,
                        bordercolor=es.SUPERFICIE, relief="flat", focuscolor=es.FOCO,
                        font=es.fuente(es.TIPO_SM), padding=(es.ESP["sm"], es.ESP["xs"]))
        style.map("Plana.TButton",
                  background=[("disabled", es.SUPERFICIE), ("pressed", es.SUPERFICIE),
                              ("active", es.SUPERFICIE_ALTA)],
                  foreground=[("disabled", es.BORDE), ("active", es.TEXTO)],
                  bordercolor=[("focus", es.FOCO)])
        style.configure("TMenubutton", background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                        focuscolor=es.FOCO, relief="flat",
                        padding=(es.ESP["sm"], es.ESP["xs"] + 1))
        style.map("TMenubutton", background=estados_fondo, foreground=estados_texto)
        style.configure("TCheckbutton", background=es.SUPERFICIE, foreground=es.TEXTO,
                        focuscolor=es.FOCO)
        style.map("TCheckbutton", background=[("active", es.SUPERFICIE)],
                  foreground=estados_texto)
        # Los campos de los diálogos salían en blanco: ttk.Entry y ttk.Combobox
        # no heredan del estilo raíz y rompían el conjunto oscuro.
        for campo in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(campo, fieldbackground=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                            background=es.SUPERFICIE_ALTA, bordercolor=es.BORDE,
                            lightcolor=es.BORDE, darkcolor=es.BORDE,
                            arrowcolor=es.TEXTO_TENUE, insertcolor=es.ACENTO,
                            selectbackground=es.SELECCION, selectforeground=es.TEXTO)
            style.map(campo,
                      fieldbackground=[("readonly", es.SUPERFICIE_ALTA),
                                       ("disabled", es.SUPERFICIE)],
                      foreground=[("disabled", es.TEXTO_TENUE)],
                      bordercolor=[("focus", es.FOCO)])
        # El desplegable del Combobox es un Listbox de Tk: solo obedece a la
        # base de datos de opciones.
        self.option_add("*TCombobox*Listbox.background", es.SUPERFICIE_ALTA)
        self.option_add("*TCombobox*Listbox.foreground", es.TEXTO)
        self.option_add("*TCombobox*Listbox.selectBackground", es.SELECCION)
        self.option_add("*TCombobox*Listbox.selectForeground", es.TEXTO)
        # Las barras de desplazamiento por defecto son claras y rompen el conjunto.
        style.configure("Vertical.TScrollbar", background=es.SUPERFICIE_ALTA,
                        troughcolor=es.SUPERFICIE, bordercolor=es.SUPERFICIE,
                        arrowcolor=es.TEXTO_TENUE, relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", es.BORDE)])
        style.configure("Horizontal.TScrollbar", background=es.SUPERFICIE_ALTA,
                        troughcolor=es.SUPERFICIE, bordercolor=es.SUPERFICIE,
                        arrowcolor=es.TEXTO_TENUE, relief="flat")

    def _text(self, parent, **kwargs):
        """Área de texto del sistema, con foco visible por teclado."""
        options = {
            "background": es.SUPERFICIE_ALTA, "foreground": es.TEXTO,
            "insertbackground": es.ACENTO, "selectbackground": es.SELECCION,
            "relief": "flat", "borderwidth": 0, "font": es.fuente(),
            # El recuadro de foco es obligatorio para navegar con teclado.
            "highlightthickness": 1, "highlightbackground": es.SUPERFICIE,
            "highlightcolor": es.FOCO,
        }
        options.update(kwargs)
        return ScrolledText(parent, **options)

    def _build(self) -> None:
        self._build_barra()
        # El pie se ancla antes que el área expansible: con pack, lo colocado
        # después es lo que se recorta al faltar espacio.
        self._build_pie()
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=es.ESP["sm"], pady=(0, es.ESP["xs"]))
        self.panes = panes
        # El artículo va primero y con más peso: es el foco del trabajo.
        self._build_editor(panes)
        self._build_asistente(panes)
        self._registrar_atajos()
        self.append("Articulador", "Cuéntame qué quieres explorar o mejorar. Puedo usar el artículo completo o una selección.", es_respuesta=False)
        self.editor.focus_set()
        # Iniciar el consumidor de eventos de UI (thread-safe)
        self.process_ui_events()

    def _build_barra(self) -> None:
        """Barra mínima: solo lo que se usa a diario. El resto, en el menú."""
        # Tk no soporta desenfoque real; esta superficie elevada compacta da la
        # misma separación visual sin efectos pesados ni recursos gráficos.
        barra = ttk.Frame(self, style="Cabecera.TFrame",
                          padding=(es.ESP["sm"], es.ESP["xs"], es.ESP["sm"], es.ESP["xs"]))
        barra.pack(fill="x")

        menu_archivo = tk.Menu(self, tearoff=False, background=es.SUPERFICIE_ALTA,
                               foreground=es.TEXTO, activebackground=es.ACENTO,
                               activeforeground=es.ACENTO_TEXTO, font=es.fuente())
        entradas: list[tuple[str, Callable[[], object], str] | None] = [
            ("Abrir artículo…", self.open_document, "Ctrl+O"),
            ("Guardar", self.save_document, "Ctrl+S"),
            ("Guardar como…", lambda: self.save_document(save_as=True), "Ctrl+Mayús+S"),
            None,
            ("Abrir proyecto…", self.open_project, ""),
            ("Guardar proyecto…", self.save_project, ""),
            None,
            ("Configurar modelo…", self.settings, ""),
            ("Referencias…", self.manage_references, ""),
            ("Limpiar conversación", self.clear_history, ""),
        ]
        for entrada in entradas:
            if entrada is None:
                menu_archivo.add_separator()
            else:
                etiqueta, orden, acelerador = entrada
                menu_archivo.add_command(label=etiqueta, command=orden, accelerator=acelerador)
        self.menu_archivo = menu_archivo
        ttk.Menubutton(barra, text="☰  Menú", menu=menu_archivo).pack(side="left")
        ttk.Button(barra, text="Guardar", style="Guardar.TButton",
                   command=self.save_document).pack(side="left", padx=(es.ESP["sm"], 0))
        self.references_button = ttk.Button(barra, text="Referencias: 0",
                                            command=self.manage_references)
        self.references_button.pack(side="left", padx=(es.ESP["sm"], 0))

        # Estado de sincronía del documento: símbolo + texto, nunca solo color.
        # Grupo de estado, separado del grupo de acciones por espacio, no por reglas.
        self.sync_label = ttk.Label(barra, text="○  Sin cambios", style="Cabecera.TLabel")
        self.sync_label.pack(side="left", padx=(es.ESP["lg"], 0))

        self.boton_panel = ttk.Button(barra, text="◧  Ocultar panel IA  (F6)",
                                      command=self.toggle_asistente)
        self.boton_panel.pack(side="right")
        self.profile_chip = ttk.Button(
            barra, text=f"Modelo: {self.profile.model or 'sin configurar'}",
            style="Plana.TButton", command=self.settings)
        self.profile_chip.pack(side="right", padx=(0, es.ESP["sm"]))

    def _build_editor(self, panes) -> None:
        editor = ttk.Labelframe(panes, text="TU ARTÍCULO", padding=es.ESP["md"])
        panes.add(editor, weight=68)
        self.panel_editor = editor
        self.editor = self._text(editor, undo=True, wrap="word", font=es.fuente(es.TIPO_LG),
                                 background=es.SUPERFICIE, padx=es.ESP["lg"], pady=es.ESP["lg"],
                                 spacing1=2, spacing2=3, spacing3=8)
        self.editor.pack(fill="both", expand=True)
        self.editor.bind("<<Modified>>", self.modified)
        self.editor.bind("<ButtonRelease-1>", lambda e: self.update_context())
        # <<Selection>> cubre también la selección con teclado (Shift+flechas), que
        # <ButtonRelease-1> no veía: sin esto la etiqueta del botón se desincroniza.
        self.editor.bind("<<Selection>>", lambda e: self.update_context())
        self.editor.bind("<KeyRelease>", lambda e: self.schedule_stats())
        self.editor.bind("<Button-3>", self.text_menu)

    def _build_asistente(self, panes) -> None:
        chat = ttk.Labelframe(panes, text="ASISTENTE", padding=es.ESP["md"])
        panes.add(chat, weight=32)
        self.panel_asistente = chat

        # Los controles se anclan abajo ANTES que el historial. Con pack, lo que
        # se coloca después es lo que se recorta al faltar espacio: al reservar
        # primero el compositor, las acciones primarias nunca desaparecen aunque
        # el panel se estreche.
        self.cost_label = tk.StringVar(value="El contexto y el coste se muestran antes de enviar.")
        ttk.Label(chat, textvariable=self.cost_label, style="TenueSuperficie.TLabel",
                  wraplength=300, justify="left").pack(side="bottom", fill="x",
                                                       pady=(es.ESP["xs"], 0))

        fila = ttk.Frame(chat, style="Superficie.TFrame")
        fila.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))
        self.cancel_button = ttk.Button(fila, text="Cancelar", command=self.cancel_request,
                                        state="disabled")
        self.cancel_button.pack(side="right", padx=(0, es.ESP["sm"]))
        self.review_button = ttk.Button(fila, text="Revisar artículo", command=self.review)
        self.review_button.pack(side="left")

        # Compositor compacto: en Tk no hay radio nativo de 8px, pero el campo y
        # la acción comparten una superficie continua y ahorran altura.
        compositor = ttk.Frame(chat, style="Alta.TFrame", padding=es.ESP["xs"])
        compositor.pack(side="bottom", fill="x")
        self.send_button = ttk.Button(compositor, text="Enviar", style="Primaria.TButton",
                                      command=self.send_message)
        self.send_button.pack(side="right", fill="y")
        self.input = self._text(compositor, height=3, wrap="word",
                                padx=es.ESP["sm"], pady=es.ESP["xs"],
                                highlightbackground=es.SUPERFICIE_ALTA)
        self.input.pack(side="left", fill="both", expand=True, padx=(0, es.ESP["xs"]))
        self.input.bind("<Return>", lambda e: self.send_message() or "break")
        self.input.bind("<Control-Return>", lambda e: self.input.insert("insert", "\n") or "break")
        self.input.bind("<Button-3>", self.text_menu)

        # Indicador de estado: símbolo + texto + color, y nombre accesible propio.
        self.estado_ayuda = tk.StringVar(value=EstadoUI.REPOSO.ayuda)
        ttk.Label(chat, textvariable=self.estado_ayuda, style="TenueSuperficie.TLabel",
                  wraplength=300, justify="left").pack(side="bottom", fill="x",
                                                       pady=(2, es.ESP["sm"]))
        self.activity = tk.StringVar(value=EstadoUI.REPOSO.etiqueta())
        self.estado_actual = EstadoUI.REPOSO
        self.estado_label = ttk.Label(chat, textvariable=self.activity,
                                      style="Superficie.TLabel",
                                      foreground=EstadoUI.REPOSO.color)
        self.estado_label.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0))

        # Confirmación de contexto en línea. Se crea oculta y solo aparece cuando
        # hay algo que decidir; sustituye al modal que salía antes de cada envío.
        self.barra_aprobacion = ttk.Frame(chat, style="Alta.TFrame",
                                          padding=(es.ESP["sm"], es.ESP["sm"]))
        self.aprobacion_texto = tk.StringVar(value="")
        ttk.Label(self.barra_aprobacion, textvariable=self.aprobacion_texto,
                  background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                  font=es.fuente(es.TIPO_SM), wraplength=300,
                  justify="left").pack(fill="x")
        acciones = ttk.Frame(self.barra_aprobacion, style="Alta.TFrame")
        acciones.pack(fill="x", pady=(es.ESP["sm"], 0))
        self.boton_aprobar = ttk.Button(acciones, text="Enviar contexto",
                                        style="Primaria.TButton")
        self.boton_aprobar.pack(side="right")
        self.boton_rechazar = ttk.Button(acciones, text="No enviar")
        self.boton_rechazar.pack(side="right", padx=(0, es.ESP["sm"]))

        self.history = self._text(chat, wrap="word", state="disabled",
                                  padx=es.ESP["md"], pady=es.ESP["sm"],
                                  background=es.SUPERFICIE_ALTA)
        self.history.pack(fill="both", expand=True)
        self.history.bind("<Button-3>", self.history_menu)
        self.history.bind("<Control-c>", lambda e: self.history.event_generate("<<Copy>>") or "break")
        # Bloques de conversación. Tk no tiene cajas con borde dentro de un Text,
        # así que la separación se expresa con fondo, sangría y margen: el turno
        # se distingue por forma y posición, no solo por el color del rótulo.
        self.history.tag_configure(
            "rotulo_usuario", foreground=es.VOZ_USUARIO, font=es.fuente(es.TIPO_SM, negrita=True),
            spacing1=es.ESP["sm"], spacing3=2, lmargin1=es.ESP["sm"], lmargin2=es.ESP["sm"])
        self.history.tag_configure(
            "cuerpo_usuario", foreground=es.TEXTO, background=es.SUPERFICIE,
            lmargin1=es.ESP["sm"], lmargin2=es.ESP["sm"], rmargin=es.ESP["sm"],
            spacing1=2, spacing2=2, spacing3=es.ESP["sm"])
        self.history.tag_configure(
            "rotulo_bot", foreground=es.VOZ_ASISTENTE, font=es.fuente(es.TIPO_SM, negrita=True),
            spacing1=es.ESP["sm"], spacing3=2, lmargin1=es.ESP["sm"], lmargin2=es.ESP["sm"])
        self.history.tag_configure(
            "cuerpo_bot", foreground=es.TEXTO,
            lmargin1=es.ESP["sm"], lmargin2=es.ESP["sm"], rmargin=es.ESP["sm"],
            spacing1=2, spacing2=2, spacing3=es.ESP["sm"])
        # Nota de sistema: ni voz del usuario ni del asistente.
        self.history.tag_configure(
            "nota", foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM),
            lmargin1=es.ESP["sm"], lmargin2=es.ESP["sm"], rmargin=es.ESP["sm"],
            spacing1=es.ESP["sm"], spacing3=es.ESP["sm"])
        self.history.tag_configure("separacion", spacing3=es.ESP["xs"])
        # Compatibilidad con los nombres antiguos de etiqueta.
        self.history.tag_configure("you", foreground=es.VOZ_USUARIO, font=es.fuente(negrita=True))
        self.history.tag_configure("bot", foreground=es.VOZ_ASISTENTE, font=es.fuente(negrita=True))

    def _build_pie(self) -> None:
        """Una sola fila con el estado a la izquierda y las métricas a la derecha.

        Las métricas del artículo vivían dentro del panel del editor, donde
        competían con el texto. Aquí forman una franja discreta y continua; con
        la ventana estrecha el estado se recorta antes que el recuento, que es
        corto y de ancho fijo.
        """
        pie = ttk.Frame(self, style="Pie.TFrame",
                        padding=(es.ESP["sm"], es.ESP["xs"]))
        pie.pack(side="bottom", fill="x")
        self.status = tk.StringVar(value="Listo.")
        ttk.Label(pie, textvariable=self.status, style="Pie.TLabel",
                  anchor="w").pack(side="left", fill="x", expand=True)
        self.editor_stats = ttk.Label(pie, text="0 palabras · 0 min de lectura",
                                      style="Pie.TLabel", anchor="e")
        self.editor_stats.pack(side="right")

    def _registrar_atajos(self) -> None:
        """Atajos globales: la interfaz debe poder manejarse solo con teclado."""
        atajos: list[tuple[str, Callable[[], object]]] = [
            ("<Control-s>", self.save_document),
            ("<Control-S>", lambda: self.save_document(save_as=True)),
            ("<Control-o>", self.open_document),
            ("<F6>", self.toggle_asistente),
            ("<Escape>", self.cancel_request),
        ]
        for secuencia, accion in atajos:
            self.bind_all(secuencia, self._manejador_atajo(accion))
        for widget in (self.editor, self.input, self.history):
            widget.bind("<Control-a>", self.select_all_text)
            widget.bind("<Control-A>", self.select_all_text)

    @staticmethod
    def _manejador_atajo(accion: Callable[[], object]) -> Callable[[object], str]:
        """Envuelve una acción como manejador de evento que detiene la propagación."""
        def manejador(_evento: object) -> str:
            accion()
            return "break"
        return manejador

    def append(self, who:str, text:str, es_respuesta: bool = True) -> None:
        """Escribe en el historial. `es_respuesta=False` para textos de orientación,
        que no deben contar como «última respuesta» copiable ni ensuciar el ámbito."""
        es_usuario = who == "Tú"
        self.history.config(state="normal")
        self.history.insert("end", f"{who}\n", "rotulo_usuario" if es_usuario else "rotulo_bot")
        self.history.insert("end", f"{text.strip()}\n", "cuerpo_usuario" if es_usuario else "cuerpo_bot")
        self.history.insert("end", "\n", "separacion")
        self.history.see("end")
        self.history.config(state="disabled")
        if who=="Articulador" and es_respuesta: self.scope.last_response=text
    def clear_history(self) -> None:
        """Limpia historial de conversación."""
        # Vaciar el historial a mitad de un streaming dejaba el texto siguiente
        # pegándose sobre un widget ya borrado y sin encabezado.
        if self.session.request_active:
            messagebox.showinfo("Consulta en curso","Espera o cancela la consulta antes de limpiar."); return
        if messagebox.askyesno("Limpiar historial", "¿Limpiar el historial de conversación?"):
            self._clear_history_widget()
            self.session.conversation.clear()
            self.scope.last_response=""; self.streaming_text=""; self.streaming_request=None
            self.status.set("Historial limpiado.")
    def set_estado(self, estado: EstadoUI, detalle: str = "") -> None:
        """Punto único donde cambia el estado visible de la conversación.

        Actualiza a la vez los tres portadores (símbolo, texto, color), el texto
        de ayuda que explica qué ocurre sin documentación, el nombre accesible
        para lectores de pantalla y la habilitación de los botones. Antes cada
        rama del flujo escribía su propia cadena y no había estado consultable.
        """
        self.estado_actual = estado
        self.activity.set(estado.etiqueta(detalle))
        self.estado_ayuda.set(estado.ayuda)
        try:
            self.estado_label.config(foreground=estado.color)
            # El nombre accesible viaja aparte del color y del símbolo.
            self.estado_label.config(text=self.activity.get())
        except tk.TclError:
            pass
        activo = estado in ESTADOS_ACTIVOS
        self.send_button.state(["disabled"] if activo else ["!disabled"])
        self.cancel_button.state(["!disabled"] if activo else ["disabled"])

    def estado_accesible(self, detalle: str = "") -> str:
        """Descripción del estado para lectores de pantalla y para pruebas."""
        return self.estado_actual.descripcion_accesible(detalle)

    def toggle_asistente(self):
        """Oculta o restaura el panel del asistente para dar todo el ancho al artículo."""
        if self.asistente_visible:
            self.panes.forget(self.panel_asistente)
            self.boton_panel.config(text="◨  Mostrar panel IA  (F6)")
            self.status.set("Asistente oculto. F6 lo vuelve a mostrar.")
            self.editor.focus_set()
        else:
            self.panes.add(self.panel_asistente, weight=32)
            self.boton_panel.config(text="◧  Ocultar panel IA  (F6)")
            self.status.set("Asistente visible.")

    @property
    def asistente_visible(self) -> bool:
        # panes() devuelve rutas Tcl (cadenas), no objetos widget: comparar el
        # widget directamente daba siempre False y el panel nunca se ocultaba.
        return str(self.panel_asistente) in self.panes.panes()
    def copy_response(self):
        if not self.scope.last_response:return
        self.clipboard_clear(); self.clipboard_append(self.scope.last_response); self.status.set("Última respuesta copiada.")
    @staticmethod
    def select_all_text(event) -> str:
        event.widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    def text_menu(self, event):
        """Menú de edición estándar para los campos editables de Tk."""
        widget = event.widget
        menu = tk.Menu(self, tearoff=False, background=es.SUPERFICIE_ALTA,
                       foreground=es.TEXTO, activebackground=es.ACENTO,
                       activeforeground=es.ACENTO_TEXTO, font=es.fuente())
        menu.add_command(label="Deshacer", command=lambda: self._edit_undo(widget))
        menu.add_command(label="Rehacer", command=lambda: self._edit_redo(widget))
        menu.add_separator()
        menu.add_command(label="Cortar", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copiar", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Pegar", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Seleccionar todo", command=lambda: widget.tag_add("sel", "1.0", "end-1c"))
        menu.add_command(label="Borrar todo", command=lambda: widget.delete("1.0", "end"))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        return "break"

    @staticmethod
    def _edit_undo(widget) -> None:
        try:
            widget.edit_undo()
        except tk.TclError:
            pass

    @staticmethod
    def _edit_redo(widget) -> None:
        try:
            widget.edit_redo()
        except tk.TclError:
            pass

    def history_menu(self,event):
        menu=tk.Menu(self,tearoff=False,background=es.SUPERFICIE_ALTA,foreground=es.TEXTO,activebackground=es.ACENTO,activeforeground=es.ACENTO_TEXTO,font=es.fuente())
        menu.add_command(label="Copiar",command=lambda:self.history.event_generate("<<Copy>>"))
        menu.add_command(label="Seleccionar todo",command=lambda:self.history.tag_add("sel","1.0","end-1c"))
        menu.tk_popup(event.x_root,event.y_root); menu.grab_release()
        return "break"
    def modified(self,_=None):
        if not self.editor.edit_modified(): return
        self.editor.edit_modified(False)
        if self._suppress_modified: return  # Carga programática, no edición del usuario.
        self.session.dirty=True; self.sync_label.config(text="●  Cambios sin guardar", foreground=es.ESTADO_AVISO); self.update_context(); self.schedule_stats()

    def _replace_editor_text(self, content: str) -> None:
        """Sustituye el contenido del editor sin que cuente como edición del usuario.

        La supresión se libera en `after_idle` porque el <<Modified>> que genera Tk
        llega como evento de ventana, siempre antes que los manejadores idle.
        """
        self._suppress_modified = True
        try:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", content)
            self.editor.edit_reset()  # El deshacer no debe cruzar documentos.
            self.editor.edit_modified(False)
        finally:
            self.after_idle(self._release_modified_suppression)

    def _release_modified_suppression(self) -> None:
        try:
            self.editor.edit_modified(False)
        except tk.TclError:
            pass
        self._suppress_modified = False
    def schedule_stats(self):
        if self.stats_after: self.after_cancel(self.stats_after)
        self.stats_after=self.after(300,self.update_stats)
    def update_context(self):
        selected=self.editor.get("sel.first","sel.last").strip() if self.editor.tag_ranges("sel") else ""
        self.status.set(f"Contexto: selección de {len(selected.split())} palabras." if selected else "Contexto: artículo completo.")
        # Revisar solo lo seleccionado es deliberado (edición granular); el botón debe
        # decir sobre qué va a actuar en vez de prometer siempre el artículo entero.
        self.review_button.config(text="Revisar selección" if selected else "Revisar artículo")
    def update_stats(self):
        self.stats_after=None; words=len(self.editor.get("1.0","end-1c").split()); self.editor_stats.config(text=f"{words:,} palabras · {max(1,round(words/220))} min de lectura" if words else "0 palabras · 0 min de lectura")
    def handle_callback_error(self, exc_type, exc_value, _traceback):
        logger.exception("Excepción no controlada de Tkinter", exc_info=(exc_type, exc_value, _traceback))
        self.status.set("Ocurrió un error interno. Puedes continuar o reiniciar Articulador.")
        messagebox.showerror("Error interno",str(exc_value),parent=self)
    def show_error(self, title: str, detail: str) -> None:
        self.status.set(title)
        messagebox.showerror(title, detail, parent=self)
    def load_document(self, path: Path) -> bool:
        """Abre un artículo estrenando ArticleSession. Retorna si tuvo éxito.

        Cada archivo empieza con sesión limpia: arrastrar la conversación entre
        documentos dejaba el historial hablando de otro texto y fue el vector del
        volcado de datos entre artículos (instantánea de revisión cruzada).
        """
        success, error, session = self.docs.open_document(path)
        if not success:
            self.show_error("No se pudo abrir el documento", f"{path}\n\n{error}")
            return False
        self.docs.set_session(session)
        self._enter_document_scope(session.document_path)
        self._replace_editor_text(session.article)
        self._clear_history_widget()
        self.append("Articulador", f"Abierto «{path.name}». Pregúntame lo que quieras sobre "
                    f"el artículo, o selecciona un fragmento para trabajar solo sobre él.",
                    es_respuesta=False)
        self.session.dirty=False; self.sync_label.config(text="○  Sin cambios", foreground=es.TEXTO_TENUE)
        self.update_context(); self.schedule_stats(); self.status.set(f"Documento abierto: {path.name}")
        return True

    def _clear_history_widget(self) -> None:
        """Vacía el panel de conversación (el estado ya vive en la sesión)."""
        self.history.config(state="normal")
        self.history.delete("1.0", "end")
        self.history.config(state="disabled")
    def send_message(self):
        message=self.input.get("1.0","end-1c").strip()
        if not message or self.session.request_active:return
        self.input.delete("1.0","end"); self.append("Tú",message); self.request(message)
    def review(self):
        """Revisa el artículo abierto, o la selección si la hay.

        La revisión NO busca referencias locales: el texto que se ve en pantalla
        ya es exactamente lo que debe recibir el modelo. Antes pasaba por el
        flujo general, así que indexaba el workspace, proponía compartir
        archivos técnicos del repositorio y se quedaba esperando una
        confirmación de privacidad que no venía a cuento.
        """
        articulo = self.editor.get("1.0", "end-1c")
        if not articulo.strip():
            messagebox.showinfo("Falta artículo", "Escribe o abre un artículo."); return
        if self.session.request_active:
            messagebox.showinfo("Consulta en curso", "Espera a que termine la consulta anterior."); return
        seleccion = self.editor.get("sel.first", "sel.last") if self.editor.tag_ranges("sel") else ""
        if seleccion.strip():
            self._solicitar_revision(seleccion, "la selección")
        else:
            self._solicitar_revision(articulo, "el artículo")

    def _solicitar_revision(self, texto: str, ambito: str) -> None:
        """Envía el texto a revisar directamente, sin contexto local ni modales."""
        if not self.profile.enabled or not self.key:
            self.append("Articulador", "Configura un perfil LLM y una key para responder."); return

        self.session.request_active = True
        self.cancel_event = threading.Event()
        cancel_event = self.cancel_event
        self.generation_counter += 1
        request_id = self.generation_counter
        self.request_types[request_id] = "review"
        # Ya está en vuelo: no hay fase de preparación de contexto que anunciar.
        self.set_estado(EstadoUI.TRANSMITIENDO, f"revisando {ambito}")

        profile = self.profile
        # El prompt técnico viaja al modelo, no al historial: es ruido ilegible.
        conversacion = [ChatMessage("user", REVIEW_PROMPT)]
        try:
            prompt = build_editor_prompt(texto, "", conversacion)
            tokens = estimate_prompt_tokens(SYSTEM_PROMPT, prompt)
            if tokens > profile.max_total_model_tokens - profile.max_output_tokens:
                self._abort_request(request_id)
                self.set_estado(EstadoUI.ERROR, "el texto a revisar es demasiado largo")
                self.show_error(
                    "Texto demasiado largo para revisar",
                    f"Entrada: ~{tokens:,} tokens\n"
                    f"Límite del modelo: ~{profile.max_total_model_tokens:,} tokens\n\n"
                    f"Selecciona un fragmento más corto y vuelve a revisar.")
                return
        except Exception as error:
            logger.error("No se pudo preparar la revisión: %s", error, exc_info=True)
            self._abort_request(request_id)
            self.set_estado(EstadoUI.ERROR, "no se pudo preparar la revisión")
            self.show_error("Error interno", "No se pudo preparar la revisión. Inténtalo de nuevo.")
            return

        api_key = self.key
        self.llm.cancel_event = cancel_event
        def work():
            self.llm.stream_response(
                profile, api_key, texto, "", conversacion,
                on_chunk=lambda chunk: self.chunks.append(request_id, chunk),
                on_error=lambda error: self.control_queue.put_nowait(("error", request_id, f"No pude responder: {error}", [])),
                on_complete=lambda result, usage: self.control_queue.put_nowait(("complete", request_id, result, [], usage, "review")),
                request_id=request_id,
                cancel_event=cancel_event,
            )
        threading.Thread(target=work, daemon=True).start()

    def request(self, message: str, request_type: str = "normal"):
        """Envía una consulta sobre el artículo, sin explorar archivos locales.

        El artículo abierto (o la selección) es el único contexto automático.
        Las referencias de archivos deben ser una acción explícita del usuario;
        buscar el workspace por cada mensaje hacía que una consulta normal se
        detuviera pidiendo permiso para compartir documentación no solicitada.
        """
        if not self.profile.enabled or not self.key: self.append("Articulador","Configura un perfil LLM y una key para responder."); return
        article = self.editor.get("1.0","end-1c")
        selected = self.editor.get("sel.first","sel.last") if self.editor.tag_ranges("sel") else article
        self.session.request_active=True; self.cancel_event=threading.Event(); self.set_estado(EstadoUI.TRANSMITIENDO)
        # Usar generation_counter global (nunca reinicia) para prevenir contaminación
        self.generation_counter += 1; request_id = self.generation_counter
        # Guardar el tipo de solicitud para este request_id
        self.request_types[request_id] = request_type
        cancel_event=self.cancel_event
        # El artículo abierto siempre se envía como artículo. Solo las referencias
        # que la persona añadió expresamente forman el paquete adicional y activan
        # la confirmación de privacidad ya existente.
        packet, files, unavailable = self._reference_packet()
        if unavailable:
            messagebox.showwarning(
                "Algunas referencias no están disponibles",
                "No se pudieron leer: " + ", ".join(unavailable) +
                "\n\nSe enviarán las referencias que sí siguen disponibles.",
                parent=self,
            )
        self.confirm_and_send(request_id, message, selected, packet, files, cancel_event)

    def _reference_packet(self) -> tuple[str, list[str], list[str]]:
        """Lee exclusivamente las referencias añadidas por la persona.

        El límite por archivo y el límite total evitan que una selección grande
        haga crecer el prompt sin control. Los nombres, no las rutas absolutas,
        son los que se envían al proveedor dentro del contenido.
        """
        remaining = min(self.profile.max_context_chars // 3, MAX_CONTEXT_PACKET_CHARS)
        parts: list[str] = []
        files: list[str] = []
        unavailable: list[str] = []
        for path in self.reference_files:
            if remaining <= 0:
                break
            try:
                with path.open("rb") as source:
                    raw = source.read(MAX_INDEXED_FILE_BYTES)
                content = raw.decode("utf-8", errors="replace")
            except OSError:
                unavailable.append(path.name)
                continue
            excerpt = content[:min(MAX_CONTEXT_EXCERPT_CHARS, remaining)]
            if not excerpt:
                continue
            parts.append(f"REFERENCIA LOCAL: {path.name}\n---\n{excerpt}")
            files.append(path.name)
            remaining -= len(excerpt)
        return "\n\n".join(parts), files, unavailable
    def context_failed(self, request_id: int, error_msg: str) -> None:
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types: return
        logger.error("No se pudo preparar el contexto: %s", error_msg)
        self.session.request_active=False; self._reset_request_ui()
        self.request_types.pop(request_id, None)
        self.set_estado(EstadoUI.ERROR, "no se pudo preparar el contexto"); self.show_error("Error de contexto", error_msg)

    def confirm_and_send(self, request_id, message, selected, packet, files, cancel_event):
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types or cancel_event.is_set(): return
        self.scope.context_files=files

        # Obtener el tipo de solicitud (normal/review) para este request_id
        request_type = self.request_types.get(request_id, "normal")

        # Instantánea única del perfil: leerlo varias veces permitiría que el diálogo
        # de configuración cambiara los límites entre la validación y el envío.
        profile = self.profile

        # Construir conversation INCLUYENDO el mensaje actual (necesario para validación y envío)
        # Tomar últimos 12 mensajes previos + el actual
        conversation_with_message = [*self.session.conversation[-12:], ChatMessage("user", message)]


        # Validar límite GLOBAL contra el payload EXACTO (fail-closed)
        try:
            # Construir el prompt COMPLETO: SYSTEM_PROMPT + JSON con todo (articulo, contexto, conversation con mensaje)
            prompt_json = build_editor_prompt(selected, packet, conversation_with_message)
            actual_tokens = estimate_prompt_tokens(SYSTEM_PROMPT, prompt_json)

            # Validar límite ENTRADA + SALIDA: entrada + max_output_tokens <= max_total_model_tokens
            # actual_tokens YA está en tokens (calculado por estimate_prompt_tokens)
            max_allowed_tokens = profile.max_total_model_tokens - profile.max_output_tokens
            if actual_tokens > max_allowed_tokens:
                self._abort_request(request_id)
                self.show_error(
                    "Solicitud demasiado grande",
                    f"Entrada: ~{actual_tokens:,} tokens\n"
                    f"Salida reservada: ~{profile.max_output_tokens:,} tokens\n"
                    f"Límite total modelo: ~{profile.max_total_model_tokens:,} tokens\n\n"
                    f"Reduce el artículo, la conversación previa o el contexto local."
                )
                return
        except Exception as e:
            # Validación fail-closed: si hay error, rechazar la solicitud
            logger.error("Error crítico validando tamaño del prompt: %s", e, exc_info=True)
            self._abort_request(request_id)
            self.show_error(
                "Error interno",
                f"No se pudo validar el tamaño de la solicitud: {e}\n\nIntenta de nuevo."
            )
            return

        # Calcular tokens para UI usando actual_tokens del payload COMPLETO
        input_tokens = actual_tokens
        output_tokens = profile.max_output_tokens
        cost = (input_tokens * profile.input_price_per_million + output_tokens * profile.output_price_per_million) / 1_000_000
        last_reasons=self.context.get_last_reasons()  # Cache para no llamar en loop
        reasons=" · ".join(f"{name} ({last_reasons.get(name, 'contexto disponible')})" for name in files)
        detail=f"Contexto: {reasons or 'sin archivos'} · ~{input_tokens:,} tokens entrada"
        if cost: detail+=f" · coste máx. ~${cost:.4f}"
        self.cost_label.set(detail)
        # Lo que el usuario aprueba son los FRAGMENTOS locales: la huella cubre el
        # paquete de contexto, no el artículo ni la conversación. Con el prompt
        # completo el hash cambiaba en cada mensaje y el diálogo salía siempre.
        content_hash = hashlib.sha256(packet.encode("utf-8")).hexdigest()[:16]
        key: ContextApprovalKey = (profile.endpoint, profile.provider, tuple(files), content_hash)

        def lanzar() -> None:
            self._lanzar_envio(request_id, profile, message, selected, packet,
                               conversation_with_message, files, request_type, cancel_event)

        if files and key not in self.approved_contexts:
            # Confirmación EN el panel, no un modal encima: no interrumpe la
            # lectura del artículo ni bloquea el bombeo de eventos.
            self._pedir_aprobacion(request_id, files, key, lanzar)
            return
        lanzar()

    def _lanzar_envio(self, request_id, profile, message, selected, packet,
                      conversation_with_message, files, request_type, cancel_event) -> None:
        """Arranca el worker de la petición ya aprobada."""
        if self.closing or request_id not in self.request_types or cancel_event.is_set():
            return
        # Agregar mensaje a session para persistencia
        self.session.conversation.append(ChatMessage("user", message))

        # Snapshot in the UI thread: the worker must not read mutable session state.
        # IMPORTANTE: usar conversation_with_message que incluye el mensaje actual
        api_key = self.key
        self.llm.cancel_event = cancel_event
        def work():
            # Usar LLMSessionManager con error handling robusto
            # Publicar eventos en queue para thread-safety (no self.after() desde thread)
            self.llm.stream_response(
                profile, api_key, selected, packet, conversation_with_message,
                on_chunk=lambda chunk: self.chunks.append(request_id, chunk),
                on_error=lambda error: self.control_queue.put_nowait(("error", request_id, f"No pude responder: {error}", files)),
                on_complete=lambda result, usage: self.control_queue.put_nowait(("complete", request_id, result, files, usage, request_type)),
                request_id=request_id,
                cancel_event=cancel_event,
            )
        threading.Thread(target=work,daemon=True).start()

    def _pedir_aprobacion(self, request_id: int, files: list[str],
                          key: ContextApprovalKey, al_aceptar) -> None:
        """Muestra la confirmación de contexto dentro del panel del asistente."""
        self.aprobacion_texto.set(
            f"Se enviarán {len(files)} archivo(s) local(es) al proveedor: "
            + ", ".join(files)
        )
        self.set_estado(EstadoUI.PREPARANDO, "esperando tu confirmación")

        def aceptar() -> None:
            self._ocultar_aprobacion()
            # Desalojar la aprobación más antigua, no las 128: vaciar el conjunto
            # entero obligaba a reconfirmar todo de golpe.
            while len(self.approved_contexts) >= 128:
                self.approved_contexts.pop(next(iter(self.approved_contexts)), None)
            self.approved_contexts[key] = None
            al_aceptar()

        def rechazar() -> None:
            self._ocultar_aprobacion()
            self._abort_request(request_id)
            self.set_estado(EstadoUI.CANCELADO, "no se envió nada")

        self.boton_aprobar.config(command=aceptar)
        self.boton_rechazar.config(command=rechazar)
        self.barra_aprobacion.pack(side="bottom", fill="x", pady=(es.ESP["sm"], 0),
                                   before=self.estado_label)
        self.boton_aprobar.focus_set()

    def _ocultar_aprobacion(self) -> None:
        if self.barra_aprobacion.winfo_ismapped():
            self.barra_aprobacion.pack_forget()

    def _abort_request(self, request_id: int) -> None:
        """Descarta una petición antes de enviarla y libera la UI por completo.

        Incluye el botón Cancelar, que al rechazar el envío quedaba habilitado
        sin ninguna petición viva detrás.
        """
        self.session.request_active = False
        self._reset_request_ui()
        self.request_types.pop(request_id, None)
        self.chunks.discard(request_id)

    def finish(self, request_id: int, result: str, files: list[str], usage=(None, None), request_type: str = "normal", is_error: bool = False):
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types: return
        self.request_types.pop(request_id, None)
        self.session.request_active=False; self._reset_request_ui()
        usage = usage or (None, None)

        # Lo ya emitido en pantalla pertenece a ESTA petición y no debe perderse.
        streamed = self.streaming_text if self.streaming_request == request_id else ""
        if self.streaming_request == request_id:
            self.streaming_request = None
        self.streaming_text = ""

        self.status.set("Contexto usado: "+", ".join(files) if files else "Respuesta lista.")
        if usage[0] is not None: self.cost_label.set(f"Uso real: {usage[0]:,} entrada · {usage[1] or 0:,} salida")

        # El tipo viaja con la petición: no hay estado de revisión persistente.
        if request_type == "review":
            self._terminar_revision(result, is_error=is_error)
            return

        if is_error:
            self.set_estado(EstadoUI.ERROR)
            if streamed.strip():
                # Antes el texto parcial quedaba cortado sin explicación y el error
                # solo aparecía en la etiqueta de actividad.
                self.session.conversation.append(ChatMessage("assistant", streamed))
                self.scope.last_response = streamed
                self._append_notice(f"[INCOMPLETO] {result}")
            else:
                self.append("Articulador", result)
            return

        self.set_estado(EstadoUI.EXITO)
        self.session.conversation.append(ChatMessage("assistant",result))
        if streamed: self.scope.last_response=result
        else: self.append("Articulador",result)

    def _terminar_revision(self, result: str, *, is_error: bool) -> None:
        """Cierra una revisión mostrando hallazgos legibles, nunca JSON.

        El resultado de una revisión es un documento técnico para la máquina. No
        entra en el historial ni en la conversación: si entrara, el usuario
        leería JSON crudo y además ese JSON viajaría como contexto en los
        mensajes siguientes.
        """
        if is_error:
            self.set_estado(EstadoUI.ERROR, "la revisión no pudo completarse")
            self._append_notice("No se pudo revisar el texto. Revisa la conexión o el modelo, "
                                "y vuelve a intentarlo.")
            return

        findings = self.parse_findings(result)
        if not findings:
            # Respuesta recibida pero inservible: se dice en lenguaje llano, sin
            # enseñar el JSON que el modelo devolvió mal.
            self.set_estado(EstadoUI.ERROR, "la respuesta no era una revisión válida")
            self._append_notice("El modelo no devolvió una revisión utilizable. "
                                "Prueba con un fragmento más corto o con otro modelo.")
            return

        self.set_estado(EstadoUI.EXITO, f"{len(findings)} hallazgo(s)")
        plural = "hallazgos" if len(findings) != 1 else "hallazgo"
        self._append_notice(f"Revisión terminada: {len(findings)} {plural}.")
        self.show_findings(findings)

    def _append_notice(self, text: str) -> None:
        """Nota de sistema en el historial, sin sobrescribir lo ya emitido.

        Voz propia, tenue: ni usuario ni asistente. La regla de 60 guiones se
        sustituye por espaciado del propio bloque, que no depende del ancho.
        """
        self.history.config(state="normal")
        self.history.insert("end", f"\n{text}\n", "nota")
        self.history.insert("end", "\n", "separacion")
        self.history.see("end")
        self.history.config(state="disabled")

    def _reset_request_ui(self) -> None:
        """Devuelve los botones al estado de reposo tras cerrar una petición."""
        self.send_button.state(["!disabled"])
        self.cancel_button.state(["disabled"])
    def stream_chunk(self, request_id, value):
        # Verificar que este request_id sigue siendo válido (no cancelado/descartado)
        if self.closing or request_id not in self.request_types:
            return
        if self.streaming_request != request_id:
            self.streaming_request = request_id
            self.streaming_text = ""
            self.history.config(state="normal")
            self.history.insert("end", "Articulador\n", "rotulo_bot")
        self.streaming_text += value
        self.history.config(state="normal")
        self.history.insert("end", value, "cuerpo_bot")
        self.history.see("end")
        self.history.config(state="disabled")
        if self.estado_actual is not EstadoUI.TRANSMITIENDO: self.set_estado(EstadoUI.TRANSMITIENDO)
    def cancel_request(self):
        if not self.session.request_active:
            return
        # Cancelar usando generation_counter (request_id actual)
        if self.cancel_event:
            self.cancel_event.set()
        self.llm.cancel(self.generation_counter)
        # Limpiar TODOS los buffers pendientes (evitar memory leak)
        self.request_types.clear()
        self.chunks.clear()  # ← Descartar texto pendiente de pintar
        self.streaming_request = None
        self.streaming_text = ""
        self.session.request_active = False
        self._reset_request_ui()
        self.set_estado(EstadoUI.CANCELADO)
        self.status.set("La respuesta tardía será descartada.")

    def process_ui_events(self):
        """Consume eventos de UI publicados por threads (thread-safe, no monopoliza UI).

        El bombeo se reprograma en `finally`: si un manejador falla y la reprogramación
        no ocurre, la aplicación sigue viva pero sorda (ninguna respuesta del modelo
        vuelve a llegar y el botón Enviar queda deshabilitado para siempre).
        """
        try:
            self._drain_ui_events()
        finally:
            if not self.closing:
                try:
                    self.after(50, self.process_ui_events)
                except tk.TclError:
                    pass  # Ventana destruida mientras se drenaba la cola.

    def _drain_ui_events(self) -> None:
        """Pinta el texto acumulado y despacha los eventos de control.

        Los chunks se recogen ANTES que el control para conservar el orden
        dentro de cada petición: el texto ya emitido se pinta antes de que su
        `complete` cierre la petición.
        """
        self._render_pending_chunks()
        for _ in range(100):
            try:
                event = self.control_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._dispatch_ui_event(event)
            except Exception:
                logger.exception("Fallo procesando evento de UI: %s", event[0])
                self._recover_from_event_failure(event)

    def _render_pending_chunks(self) -> None:
        """Vuelca el texto acumulado por los workers desde el ciclo anterior.

        Coalescencia natural: cuanto más se retrase la interfaz, más texto trae
        cada vuelta, no más eventos que procesar.
        """
        for request_id, texto in self.chunks.take_all():
            # Los chunks tardíos de una petición cancelada se descartan aquí, y
            # los de una revisión no se pintan: su contenido es JSON técnico que
            # solo debe llegar al diálogo de hallazgos.
            if self.request_types.get(request_id) == "normal":
                self.stream_chunk(request_id, texto)

    def _recover_from_event_failure(self, event) -> None:
        """Desbloquea la UI cuando el manejador de un evento murió a medio camino."""
        request_id = event[1] if len(event) > 1 and isinstance(event[1], int) else None
        if request_id is not None:
            self.request_types.pop(request_id, None)
            self.chunks.discard(request_id)
            if self.streaming_request == request_id:
                self.streaming_request = None
        self._reset_request_ui()
        try:
            self.set_estado(EstadoUI.ERROR, "fallo interno al procesar la respuesta")
        except tk.TclError:
            pass

    def _dispatch_ui_event(self, event) -> None:
        """Despacha un evento de CONTROL. Los chunks no pasan por aquí."""
        event_type = event[0]

        if event_type == "error":
            _, request_id, error_msg, files = event
            # El tipo se consulta, no se asume: con "normal" fijo, el fallo de una
            # revisión se cerraba por la rama de conversación y enseñaba el texto
            # técnico del error en vez del mensaje humano.
            tipo = self.request_types.get(request_id, "normal")
            self._flush_pending_chunks(request_id)
            self.finish(request_id, error_msg, files, (None, None), tipo, is_error=True)

        elif event_type == "complete":
            _, request_id, result, files, usage, request_type = event
            self._flush_pending_chunks(request_id)
            self.finish(request_id, result, files, usage, request_type)

        elif event_type == "context_failed":
            _, request_id, error_msg = event
            self.chunks.discard(request_id)
            self.context_failed(request_id, error_msg)

        elif event_type == "confirm_and_send":
            _, request_id, message, selected, packet, files, cancel_event = event
            self.confirm_and_send(request_id, message, selected, packet, files, cancel_event)

    def _flush_pending_chunks(self, request_id: int) -> None:
        """Vuelca lo acumulado de una petición antes de cerrarla.

        Garantiza que ningún fragmento recibido se pierda por llegar el
        `complete` en el mismo ciclo que los últimos chunks.
        """
        texto = self.chunks.take(request_id)
        if texto and self.request_types.get(request_id) == "normal":
            self.stream_chunk(request_id, texto)

    parse_findings = staticmethod(parse_findings)
    def show_findings(self,findings):
        # Una revisión a la vez: sin esto cada «Revisar» dejaba otro Toplevel vivo.
        self._close_review_dialogs()
        self.review_dialogs.append(show_review_dialog(self, findings))

    def _close_review_dialogs(self) -> None:
        """Cierra los diálogos de revisión abiertos y olvida los ya destruidos."""
        for dialog in self.review_dialogs:
            try:
                if dialog.winfo_exists():
                    dialog.destroy()
            except tk.TclError:
                pass
        self.review_dialogs = []
    def snapshot_for_undo(self, text: str) -> None:
        """Guarda el "antes" de una sugerencia dentro del ámbito del documento."""
        self.scope.review_before = text

    def undo_review(self):
        if not self.scope.review_before:return
        # El deshacer solo es válido sobre el documento del que se tomó la instantánea:
        # sin esta comprobación volcaba el artículo anterior sobre el actual y lo
        # marcaba como sucio, a un Ctrl+S de destruirlo.
        if not self.scope.owns(self.session.document_path):
            self.scope.review_before=""
            self.status.set("El ajuste a deshacer pertenece a otro documento."); return
        self.editor.delete("1.0","end"); self.editor.insert("1.0",self.scope.review_before); self.scope.review_before=""; self.session.dirty=True; self.status.set("Último ajuste de revisión deshecho.")
    def open_document(self):
        # Cancelar cualquier solicitud activa antes de cambiar de documento
        if self.session.request_active:
            if not messagebox.askyesno("Solicitud activa", "¿Cancelar la consulta en curso?"):
                return
            self._cancel_active_request()

        # Verificar cambios sin guardar antes de abrir otro documento
        if self.session.dirty and not messagebox.askyesno("Cambios sin guardar", "¿Descartar cambios locales?"):
            return
        path=filedialog.askopenfilename(filetypes=[("Markdown", "*.md *.txt")])
        if path:
            # La lectura y el manejo de errores viven en DocumentManager: aquí solo
            # se decide qué archivo abrir.
            self.load_document(Path(path))
    def context_dialog(self):
        show_context_dialog(self)

    def _update_references_button(self) -> None:
        self.references_button.config(text=f"Referencias: {len(self.reference_files)}")

    def _add_references(self, paths: tuple[str, ...] | list[str]) -> int:
        """Añade archivos de referencia sin alterar el artículo del editor."""
        added = 0
        active_path = self.session.document_path.resolve() if self.session.document_path else None
        known = set(self.reference_files)
        for raw_path in paths:
            try:
                path = Path(raw_path).resolve()
            except OSError:
                continue
            if (not path.is_file() or path.suffix.lower() not in {".md", ".txt"}
                    or path == active_path or path in known):
                continue
            self.reference_files.append(path)
            known.add(path)
            added += 1
        self._update_references_button()
        return added

    def manage_references(self) -> None:
        """Permite conservar varios artículos de apoyo durante esta sesión."""
        dialog = tk.Toplevel(self)
        dialog.title("Referencias para el asistente")
        dialog.transient(self)
        dialog.configure(bg=es.SUPERFICIE)
        dialog.minsize(460, 280)
        dialog.geometry("580x360")
        frame = ttk.Frame(dialog, style="Superficie.TFrame", padding=es.ESP["lg"])
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Referencias incluidas en las consultas", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(frame, text=("Añade artículos anteriores (.md o .txt). Se mantienen durante esta sesión "
                               "y se enviarán solo cuando confirmes el contexto."),
                  style="TenueSuperficie.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(es.ESP["xs"], es.ESP["sm"]))
        # La fila de acciones se reserva ANTES de la lista expansible: con pack,
        # lo colocado después es lo que se recorta al estrechar la ventana.
        actions = ttk.Frame(frame, style="Superficie.TFrame")
        actions.pack(side="bottom", fill="x", pady=(es.ESP["lg"], 0))
        entries = tk.Listbox(frame, selectmode="extended", background=es.SUPERFICIE_ALTA,
                             foreground=es.TEXTO, selectbackground=es.SELECCION,
                             selectforeground=es.TEXTO, relief="flat", highlightthickness=1,
                             highlightbackground=es.BORDE, highlightcolor=es.FOCO,
                             font=es.fuente())
        entries.pack(fill="both", expand=True)

        def refresh() -> None:
            entries.delete(0, "end")
            for path in self.reference_files:
                entries.insert("end", str(path))

        def add() -> None:
            paths = filedialog.askopenfilenames(
                parent=dialog, title="Añadir artículos de referencia",
                filetypes=[("Artículos", "*.md *.txt"), ("Todos los archivos", "*.*")],
            )
            # Tk declara una cadena vacía al cancelar, aunque normalmente devuelve
            # una tupla. No iterar esa cadena evita tratar cada carácter como ruta.
            selected_paths = paths if isinstance(paths, tuple) else ()
            count = self._add_references(selected_paths)
            refresh()
            if count:
                self.status.set(f"{count} referencia(s) añadida(s).")

        def remove() -> None:
            selected = list(entries.curselection())
            if not selected:
                return
            self.reference_files = [path for index, path in enumerate(self.reference_files)
                                    if index not in selected]
            self._update_references_button()
            refresh()
            self.status.set("Referencias actualizadas.")

        # Acción primaria a la derecha, como en el resto de diálogos.
        ttk.Button(actions, text="Añadir archivos…", style="Primaria.TButton",
                   command=add).pack(side="right")
        ttk.Button(actions, text="Quitar seleccionadas", command=remove).pack(
            side="right", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="left")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        refresh()
        entries.focus_set()
    def save_document(self, save_as: bool = False)->bool:
        previous_path = self.session.document_path
        if save_as or previous_path is None:
            options: dict = {"defaultextension": ".md", "filetypes": [("Markdown","*.md")]}
            if previous_path is not None:
                options["initialdir"] = str(previous_path.parent)
                options["initialfile"] = previous_path.name
            path=filedialog.asksaveasfilename(**options)
            if not path:return False
            self.session.document_path=Path(path).resolve()

        # Actualizar contenido desde el editor
        self.session.article = self.editor.get("1.0","end-1c")

        # Usar DocumentManager para guardado atómico con error handling
        success, error = self.docs.save_document(self.session)
        if not success:
            # No dejar apuntando a un destino que no se pudo escribir: el siguiente
            # "Guardar" volvería a fallar en silencio contra la misma ruta.
            self.session.document_path = previous_path
            messagebox.showerror("Error al guardar", f"No se pudo guardar el documento: {error}")
            return False

        # "Guardar como…" renombra el destino sin cambiar de artículo: el ámbito
        # sigue siendo el mismo y debe seguir a la ruta nueva, o el deshacer de
        # revisión se creería huérfano.
        self.scope.document_path = self.session.document_path

        # Marcar como guardado y actualizar UI
        self.sync_label.config(text="✓  Guardado", foreground=es.ESTADO_EXITO)
        self.status.set("Artículo guardado.")
        return True
    def save_project(self):
        if self.session.dirty and not self.save_document():return
        if self.session.document_path is None:
            messagebox.showinfo("Falta el artículo","Guarda primero el artículo Markdown."); return
        options: dict = {"defaultextension": ".articulador.json", "filetypes": [("Proyecto","*.articulador.json")]}
        # El proyecto guarda rutas relativas: proponer la carpeta del artículo evita
        # la ruta imposible (el artículo debe quedar bajo la carpeta del proyecto).
        options["initialdir"] = str(self.session.document_path.parent)
        options["initialfile"] = f"{self.session.document_path.stem}.articulador.json"
        path=filedialog.asksaveasfilename(**options)
        if path:
            # Persistencia a través del DocumentManager: era el dueño declarado de esta
            # responsabilidad, pero la app llamaba a storage por su cuenta y mantenía
            # una segunda implementación del mismo flujo.
            success, error = self.docs.save_project(self.session, Path(path))
            if success:
                self.status.set("Proyecto guardado.")
            else:
                messagebox.showerror(
                    "Error al guardar proyecto",
                    f"No se pudo guardar el proyecto:\n{error}"
                )
                logger.error("Error guardando proyecto: %s", error)
    def open_project(self):
        # Cancelar cualquier solicitud activa antes de cambiar de proyecto
        if self.session.request_active:
            if not messagebox.askyesno("Solicitud activa", "¿Cancelar la consulta en curso?"):
                return
            self._cancel_active_request()

        # Verificar cambios sin guardar antes de abrir otro proyecto
        if self.session.dirty and not messagebox.askyesno("Cambios sin guardar", "¿Descartar cambios locales?"):
            return
        path=filedialog.askopenfilename(filetypes=[("Proyecto Articulador","*.articulador.json")])
        if not path:return
        # Carga a través del DocumentManager: el flujo estaba duplicado aquí y allí,
        # con manejo de errores divergente y la copia del manager sin usar ni probar.
        success, error, session = self.docs.open_project(Path(path))
        if not success:
            messagebox.showerror("Proyecto no válido", error); return
        self.docs.set_session(session)
        self._replace_editor_text(self.session.article)
        self._clear_history_widget()
        for item in self.session.conversation:self.append("Tú" if item.role=="user" else "Articulador",item.content)
        self._enter_document_scope(self.session.document_path)
        self.session.dirty=False; self.sync_label.config(text="○  Sin cambios", foreground=es.TEXTO_TENUE)
        self.update_context(); self.schedule_stats()
        self.status.set("Proyecto abierto.")

    def _enter_document_scope(self, document_path: Path | None) -> None:
        """Entra en el ámbito de un documento reemplazando el anterior por completo.

        Sustituir el objeto en vez de limpiar campo a campo es lo que hace
        imposible olvidarse de uno: cualquier campo nuevo de DocumentScope se
        renueva aquí sin tocar este método.

        `approved_contexts` queda fuera a propósito: su clave es (endpoint,
        proveedor, archivos, huella del paquete), todo derivado del workspace y
        no del artículo abierto. Vaciarlo añadiría un modal por documento.
        """
        self._close_review_dialogs()
        self.scope = DocumentScope(document_path=document_path)
    def settings(self):
        show_settings_dialog(self)

    def _cancel_active_request(self):
        """Cancela la solicitud activa e invalida su request_id."""
        if self.cancel_event:
            self.cancel_event.set()
        # Limpiar TODOS los buffers pendientes (evitar memory leak)
        self.request_types.clear()
        self.chunks.clear()  # ← Descartar texto pendiente de pintar
        self.streaming_request = None
        self.streaming_text = ""
        # Cancelar en LLMClient
        self.llm.cancel(self.generation_counter)
        self.session.request_active = False
        self._reset_request_ui()

    def close(self):
        if self.session.dirty and not messagebox.askyesno("Cambios sin guardar","¿Cerrar sin guardar?"):return
        self.closing=True
        # Cancelar cualquier solicitud activa
        if self.session.request_active:
            self._cancel_active_request()
        self.destroy()
