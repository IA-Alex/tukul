from __future__ import annotations

import os
import queue
import re
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from articulador_core import storage
from articulador_core.autosave import clear_autosave, read_autosave, write_autosave
from articulador_core.config_validator import validate_startup_config
from articulador_core.llm import SYSTEM_PROMPT, estimate_prompt_tokens
from articulador_core.logging_config import setup_logging
from articulador_core.models import ArticleSession, ChatMessage, LlmProfile
from articulador_core.prompting import build_editor_prompt
from articulador_core.review import parse_findings
from articulador_ui import estilo as es
from articulador_ui import ui_state
from articulador_ui.chunk_buffer import ChunkBuffer
from articulador_ui.context_approval import ContextApprovalCache, ContextApprovalKey
from articulador_ui.dialogs import show_review_dialog, show_settings_dialog
from articulador_ui.document_manager import DocumentManager
from articulador_ui.document_scope import DocumentScope
from articulador_ui.estado import ESTADOS_ACTIVOS, EstadoUI
from articulador_ui.llm_session_manager import LLMSessionManager
from articulador_ui.tooltip import ToolTip

# Límites del paquete de artículos de contexto que acompaña al artículo activo.
# Vivían en articulador_core/context.py junto al índice BM25; al retirar ese
# índice, las constantes se quedaron aquí, donde se usan de verdad.
MAX_CONTEXT_PACKET_CHARS = 12_000
MAX_CONTEXT_EXCERPT_CHARS = 3_000
MAX_INDEXED_FILE_BYTES = 50_000
# Frecuencia del respaldo de recuperación: se escribe solo cuando hay cambios.
AUTOSAVE_INTERVAL_MS = 5000


@dataclass(frozen=True)
class ContextArticle:
    """Instantánea explícita de un artículo que acompañará al artículo activo."""

    source_id: str
    label: str
    content: str

# Compatibilidad con los diálogos, que leían `app.COLORS`: ahora es una
# instantánea regenerada en cada `_theme()` desde `es.colores()` (el sistema
# visual vive en articulador_ui/estilo.py y es la fuente única de color).
REVIEW_PROMPT = (
    'Revisa el artículo y responde SOLO JSON válido: '
    '{"findings":[{"category":"ortografía|gramática|semántica|redundancia|estructura",'
    '"severity":"alta|media|baja","original":"fragmento exacto","suggestion":"reemplazo",'
    '"reason":"breve"}]}. Máximo 12 hallazgos. No inventes fragmentos.'
)
logger = setup_logging()


class ArticuladorApp(tk.Tk):
    """Ventana principal: widgets, estado, streaming y ciclo de vida de la sesión."""

    def __init__(self, config_path: Path = storage.CONFIG_PATH) -> None:
        super().__init__()
        self.title("Articulador")
        self.config_path = config_path
        # Estado de interfaz persistente: zoom, geometría, tema, recientes y
        # conversaciones. Vive junto al config para que una instalación tenga un
        # único directorio de estado y los tests puedan aislarlo.
        self.ui_state = storage.load_ui_state(config_path)
        # El zoom se aplica antes del tema para que las fuentes nazcan escaladas.
        es.ZOOM = self._zoom_validado(self.ui_state.get("zoom"))
        # El tema se valida de forma defensiva antes de pintar nada: un valor
        # extraño (o un estado.json corrupto) nunca rompe el arranque.
        self.theme = self._tema_validado(self.ui_state.get("theme"))
        # El tamaño se calcula UNA vez, aquí y de forma síncrona. Antes se fijaba
        # un valor y 100 ms después un `after` lo sobrescribía, pisando también
        # cualquier geometría que el usuario o quien integra la app hubiera
        # establecido entretanto.
        self._aplicar_tamano_inicial()
        self._restaurar_geometria()
        self.recent_paths = self._recientes_validados(self.ui_state.get("recent"))
        self._foco_activo = False
        self._foco_previo_asistente = True

        # LLM profiles
        self.profiles, self.active_profile = storage.load_profiles(config_path)
        # Auditoría de arranque: deja en el log por qué un perfil no responderá,
        # sin interrumpir con diálogos al abrir.
        validate_startup_config(self.profiles, self.active_profile)
        self.session_keys: dict[str, str] = {}
        self._session_keys_max = 32

        # Managers (refactorización de responsabilidades)
        self.docs = DocumentManager()
        self.llm = LLMSessionManager()

        # Session & UI state (referencia dinámica a través de property)
        # dict-como-conjunto-ordenado: autorizaciones de contexto por destino
        # (endpoint, proveedor y modelo), con desalojo FIFO real.
        self.approved_contexts = ContextApprovalCache()
        # Todo el estado derivado del documento vive en un único objeto que se
        # reemplaza entero al cambiar de artículo (ver DocumentScope).
        self.scope = DocumentScope()
        # Referencias elegidas de forma explícita. No pertenecen al documento
        # activo ni se descubren recorriendo el workspace: permanecen durante
        # esta sesión hasta que la persona las quite.
        self.context_articles: list[ContextArticle] = []
        self.review_dialogs: list[tk.Toplevel] = []
        self.stats_after: str | None = None
        self.autosave_after: str | None = None
        self._ui_events_after: str | None = None
        self.report_callback_exception = self.handle_callback_error
        self.cancel_event: threading.Event | None = None
        # Hilos daemon de peticiones en curso (review/request), para poder
        # esperarlos brevemente en destroy() antes de tirar la ventana de Tk.
        # Sin esto, un hilo que todavía no había arrancado a ejecutarse podía
        # seguir vivo tras el cierre y chocar con Tcl desde otro hilo.
        self._worker_threads: list[threading.Thread] = []
        self.streaming_request: int | None = None
        self.streaming_text = ""
        self.closing = False
        # Tk encola <<Modified>> de forma asíncrona: sin esta bandera, el documento
        # recién abierto se marcaba como "Cambios sin guardar" en el ciclo siguiente.
        self._suppress_modified = False
        # Estado visible del rótulo de sincronía del documento (clean/dirty/saved):
        # se repinta al cambiar de tema conservando el estado real del documento.
        self._sync_estado = "clean"
        # Diálogos abiertos que deben repintarse al cambiar de tema: pares
        # (ventana ancla, cómo reaplicar). Se podan solos al destruirse.
        self._reaplicar_tema_hooks: list[tuple[tk.Misc, Callable[[], None]]] = []

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
    def profile(self) -> LlmProfile:
        """Perfil LLM activo."""
        return self.profiles[self.active_profile]
    @property
    def key(self) -> str:
        """API key en vigor: variable de entorno > key de sesión > llavero."""
        return os.environ.get(self.profile.api_key_env) or self.session_keys.get(self.active_profile, "") or storage.load_key(self.active_profile)

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

    @staticmethod
    def _zoom_validado(valor: object) -> float:
        """Convierte el zoom persistido a un factor acotado; 1.0 ante basura."""
        try:
            zoom = float(valor)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0
        return max(es.ZOOM_MIN, min(es.ZOOM_MAX, zoom))

    @staticmethod
    def _recientes_validados(valor: object) -> list[str]:
        """Filtra la lista de recientes persistida a rutas útiles, con tope."""
        if not isinstance(valor, list):
            return []
        return [ruta for ruta in valor if isinstance(ruta, str) and ruta][:10]

    def _restaurar_geometria(self) -> None:
        """Restaura la geometría sin permitir que la ventana desaparezca.

        Una geometría guardada puede venir de otro monitor, de un cambio de
        resolución o de una sesión remota. Tk acepta esos valores sin error,
        pero el resultado puede dejar controles esenciales fuera del viewport.
        Se conserva el tamaño/posición cuando caben y se corrigen de forma
        defensiva cuando no.
        """
        guardada = self.ui_state.get("geometry")
        if not isinstance(guardada, str) or not guardada.strip():
            return

        coincidencia = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", guardada.strip())
        if coincidencia is None:
            return

        ancho, alto, x, y = (int(valor) for valor in coincidencia.groups())
        pantalla_ancho = self.winfo_screenwidth()
        pantalla_alto = self.winfo_screenheight()
        if pantalla_ancho <= 100 or pantalla_alto <= 100:
            return

        # Mantiene un margen visible para que la barra del sistema y los
        # bordes no oculten la ventana completa en escritorios pequeños.
        ancho = min(max(ancho, 720), max(720, pantalla_ancho - 32))
        alto = min(max(alto, 540), max(540, pantalla_alto - 64))
        x = min(max(x, 0), max(0, pantalla_ancho - ancho))
        y = min(max(y, 0), max(0, pantalla_alto - alto))
        self.geometry(f"{ancho}x{alto}+{x}+{y}")

    @staticmethod
    def _tema_validado(valor: object) -> str:
        """Convierte el tema persistido a uno válido; 'dark' ante basura."""
        return es.tema_validado(valor)

    def _theme(self) -> None:
        """Aplica el sistema visual del tema activo: un fondo, dos superficies.

        Los estilos ttk se repintan en bloque; los widgets Tk con colores
        directos se reconfiguran en `_reaplicar_estilos_widgets` sin destruir
        ni recrear nada.
        """
        es.aplicar_tema(self.theme)
        self.COLORS = es.colores()
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
                  bordercolor=[("focus", es.ACENTO_TEXTO), ("disabled", es.SUPERFICIE_ALTA)])
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
        self._reaplicar_estilos_widgets()

    def _cambiar_tema(self) -> None:
        """Alterna entre oscuro y claro desde el botón de la barra."""
        self._aplicar_tema("light" if self.theme == "dark" else "dark")

    def _aplicar_tema(self, nombre: object) -> None:
        """Activa un tema y reaplica el sistema visual sin reconstruir la ventana.

        El cambio es inmediato: no se recrea la ventana, no se tocan el editor,
        el historial, la selección, el scroll, la petición LLM ni los diálogos
        abiertos (solo se repintan). La preferencia se persiste al instante con
        `_guardar_preferencia_tema`: no depende del cierre limpio de la app.
        """
        self.theme = es.tema_validado(nombre)
        self._theme()
        self._actualizar_boton_tema()
        nombre_humano = "claro" if self.theme == "light" else "oscuro"
        self.status.set(f"Tema {nombre_humano} activado.")
        self._guardar_preferencia_tema()

    def _actualizar_boton_tema(self) -> None:
        """Mantiene el botón coherente: la etiqueta anuncia la acción, no el color."""
        if not hasattr(self, "boton_tema") or self.boton_tema is None:
            return
        if self.theme == "light":
            etiqueta = "☾  Cambiar a oscuro"
            tooltip = "Cambiar a tema oscuro (actual: claro)"
        else:
            etiqueta = "☀  Cambiar a claro"
            tooltip = "Cambiar a tema claro (actual: oscuro)"
        self.boton_tema.config(text=etiqueta)
        if getattr(self, "tooltip_tema", None) is not None:
            self.tooltip_tema.set_texto(tooltip)

    def _sincronizar_estado_sync(self, estado: str) -> None:
        """Rótulo del documento: símbolo + texto + color, nunca solo color."""
        self._sync_estado = estado
        if estado == "dirty":
            texto, color = "●  Cambios sin guardar", es.ESTADO_AVISO
        elif estado == "saved":
            texto, color = "✓  Guardado", es.ESTADO_EXITO
        else:
            texto, color = "○  Sin cambios", es.TEXTO_TENUE
        self.sync_label.config(text=texto, foreground=color)

    def _configurar_tags_historial(self) -> None:
        """Colores y fuentes de los bloques del historial (se reaplican al cambiar de tema)."""
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
        self.history.tag_configure(
            "nota", foreground=es.TEXTO_TENUE, font=es.fuente(es.TIPO_SM),
            lmargin1=es.ESP["sm"], lmargin2=es.ESP["sm"], rmargin=es.ESP["sm"],
            spacing1=es.ESP["sm"], spacing3=es.ESP["sm"])
        self.history.tag_configure("separacion", spacing3=es.ESP["xs"])
        # Compatibilidad con los nombres antiguos de etiqueta.
        self.history.tag_configure("you", foreground=es.VOZ_USUARIO, font=es.fuente(negrita=True))
        self.history.tag_configure("bot", foreground=es.VOZ_ASISTENTE, font=es.fuente(negrita=True))

    def _reaplicar_estilos_widgets(self) -> None:
        """Reaplica colores directos (Tk) a los widgets ya creados.

        Los estilos ttk se repintan solos al reconfigurar `ttk.Style`; los
        widgets Tk (Text/ScrolledText, Listbox, Menus) reciben colores por
        `.configure()` y hay que volver a aplicárselos sin destruirlos.
        """
        if getattr(self, "editor", None) is not None and self.editor.winfo_exists():
            self.editor.configure(background=es.SUPERFICIE, foreground=es.TEXTO,
                                  insertbackground=es.ACENTO, selectbackground=es.SELECCION,
                                  highlightbackground=es.SUPERFICIE, highlightcolor=es.FOCO)
        if getattr(self, "input", None) is not None and self.input.winfo_exists():
            self.input.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                                 insertbackground=es.ACENTO, selectbackground=es.SELECCION,
                                 highlightbackground=es.SUPERFICIE_ALTA, highlightcolor=es.FOCO)
        if getattr(self, "history", None) is not None and self.history.winfo_exists():
            self.history.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                                   insertbackground=es.ACENTO, selectbackground=es.SELECCION,
                                   highlightbackground=es.SUPERFICIE, highlightcolor=es.FOCO)
            self._configurar_tags_historial()
        # Etiqueta de aprobación de contexto: colores directos sobre ttk.Label.
        if getattr(self, "aprobacion_label", None) is not None and self.aprobacion_label.winfo_exists():
            self.aprobacion_label.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO)
        # Estado del documento: símbolo + texto + color (nunca solo color).
        if getattr(self, "sync_label", None) is not None and self.sync_label.winfo_exists():
            self._sincronizar_estado_sync(getattr(self, "_sync_estado", "clean"))
        # Estado de conversación: se repinta el color vigente; el resto viaja aparte.
        estado_actual = getattr(self, "estado_actual", None)
        if estado_actual is not None and getattr(self, "estado_label", None) is not None:
            if self.estado_label.winfo_exists():
                self.estado_label.config(foreground=estado_actual.color)
        self._reaplicar_tema_menus()
        self._reaplicar_tema_dialogos()

    def _reaplicar_tema_menus(self) -> None:
        """Repinta los menús Tk de la barra (no obedecen a ttk.Style)."""
        for menu in (getattr(self, "menu_archivo", None), getattr(self, "menu_recientes", None)):
            if menu is None:
                continue
            try:
                menu.config(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                            activebackground=es.ACENTO, activeforeground=es.ACENTO_TEXTO)
            except tk.TclError:
                pass

    def _registrar_reaplicar_tema(self, ancla: tk.Misc, reaplicar: Callable[[], None]) -> None:
        """Registra cómo repintar un diálogo abierto cuando cambie el tema.

        `ancla` es la ventana (Toplevel) que da de alta el cierre: cuando se
        destruye, el gancho se poda solo en la siguiente reaplicación.
        """
        self._reaplicar_tema_hooks.append((ancla, reaplicar))

    def _reaplicar_tema_dialogos(self) -> None:
        """Reaplica el tema a los diálogos abiertos sin recrearlos ni perder su estado."""
        vivos: list[tuple[tk.Misc, Callable[[], None]]] = []
        for ancla, reaplicar in self._reaplicar_tema_hooks:
            try:
                if ancla.winfo_exists():
                    reaplicar()
                    vivos.append((ancla, reaplicar))
            except tk.TclError:
                pass  # El diálogo se destruyó; se olvida en la siguiente pasada.
        self._reaplicar_tema_hooks = vivos

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
        # Los anchos solicitados por los controles del asistente pueden hacer
        # que ttk ignore la proporción declarada en `add(weight=...)`. Medir el
        # layout una vez antes de mostrar la ventana conserva la jerarquía
        # editorial; después la persona puede arrastrar el divisor normalmente.
        self.update_idletasks()
        self._alinear_panes_iniciales()
        self._registrar_atajos()
        # Estado persistido: el panel puede nacer oculto si así se dejó la última vez.
        if self.ui_state.get("panel_visible") is False:
            self.toggle_asistente()
        self.append("Articulador", "Cuéntame qué quieres explorar o mejorar. Puedo usar el artículo completo o una selección.", es_respuesta=False)
        self.editor.focus_set()
        # Iniciar el consumidor de eventos de UI (thread-safe)
        self.process_ui_events()

    def _alinear_panes_iniciales(self) -> None:
        """Da al artículo la mayor superficie inicial del espacio de trabajo."""
        if not self.panes.winfo_exists() or not self.asistente_visible:
            return
        ancho = self.panes.winfo_width()
        if ancho > 0:
            try:
                self.panes.sashpos(0, round(ancho * 0.68))
            except tk.TclError:
                pass

    def _build_barra(self) -> None:
        """Barra mínima: solo lo que se usa a diario. El resto, en el menú."""
        # Tk no soporta desenfoque real; esta superficie elevada compacta da la
        # misma separación visual sin efectos pesados ni recursos gráficos.
        self.barra = ttk.Frame(self, style="Cabecera.TFrame",
                               padding=(es.ESP["sm"], es.ESP["xs"], es.ESP["sm"], es.ESP["xs"]))
        self.barra.pack(fill="x")

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
            ("Contexto de artículos…", self.manage_references, ""),
            ("Limpiar conversación", self.clear_history, ""),
        ]
        for entrada in entradas:
            if entrada is None:
                menu_archivo.add_separator()
            else:
                etiqueta, orden, acelerador = entrada
                menu_archivo.add_command(label=etiqueta, command=orden, accelerator=acelerador)
        # Recientes: un submenú vivo, justo tras «Guardar como…».
        self.menu_recientes = tk.Menu(menu_archivo, tearoff=False, background=es.SUPERFICIE_ALTA,
                                      foreground=es.TEXTO, activebackground=es.ACENTO,
                                      activeforeground=es.ACENTO_TEXTO, font=es.fuente())
        menu_archivo.insert_cascade(3, label="Recientes", menu=self.menu_recientes)
        self.menu_archivo = menu_archivo
        self._refrescar_menu_recientes()

        self.boton_menu = ttk.Menubutton(self.barra, text="☰  Menú", menu=menu_archivo)
        self.boton_menu.pack(side="left")
        self.boton_guardar = ttk.Button(self.barra, text="Guardar", style="Guardar.TButton",
                                        command=self.save_document)
        self.boton_guardar.pack(side="left", padx=(es.ESP["sm"], 0))
        self.references_button = ttk.Button(self.barra, text="Contexto: 0 artículos",
                                            style="Plana.TButton",
                                            command=self.manage_references)
        self.references_button.pack(side="left", padx=(es.ESP["sm"], 0))

        # Estado de sincronía del documento: símbolo + texto, nunca solo color.
        # Grupo de estado, separado del grupo de acciones por espacio, no por reglas.
        self.sync_label = ttk.Label(self.barra, text="○  Sin cambios", style="Cabecera.TLabel")
        self.sync_label.pack(side="left", padx=(es.ESP["lg"], 0))

        self.boton_panel = ttk.Button(self.barra, text="◧  Ocultar panel IA  (F6)",
                                      command=self.toggle_asistente)
        self.boton_panel.pack(side="right")
        # Acción secundaria de tema: visible en la barra, operable con teclado y
        # con tooltip. La etiqueta anuncia la acción (y de paso el tema vigente).
        self.boton_tema = ttk.Button(self.barra, style="Plana.TButton",
                                     command=self._cambiar_tema)
        self.boton_tema.pack(side="right", padx=(0, es.ESP["sm"]))
        self.profile_chip = ttk.Button(
            self.barra, text=f"Modelo: {self.profile.model or 'sin configurar'}",
            style="Plana.TButton", command=self.settings)
        self.profile_chip.pack(side="right", padx=(0, es.ESP["sm"]))
        self._actualizar_boton_tema()

        ToolTip(self.boton_menu, "Archivo: abrir, guardar y proyectos")
        ToolTip(self.boton_guardar, "Guardar el artículo (Ctrl+S)")
        ToolTip(self.references_button, "Gestionar los artículos de contexto")
        ToolTip(self.boton_panel, "Mostrar u ocultar el panel IA (F6)")
        self.tooltip_tema = ToolTip(self.boton_tema, "Cambiar de tema claro/oscuro")
        self._actualizar_boton_tema()
        ToolTip(self.profile_chip, "Cambiar el modelo y sus ajustes")

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
        self.cost_label = tk.StringVar(value="Se enviará el artículo activo; el contexto adicional se confirma antes de enviar.")
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

        self.history = self._text(chat, wrap="word", state="disabled",
                                  padx=es.ESP["md"], pady=es.ESP["sm"],
                                  background=es.SUPERFICIE_ALTA)
        self.history.pack(fill="both", expand=True)
        self.history.bind("<Button-3>", self.history_menu)
        self.history.bind("<Control-c>", lambda e: self.history.event_generate("<<Copy>>") or "break")
        # Bloques de conversación. Tk no tiene cajas con borde dentro de un Text,
        # así que la separación se expresa con fondo, sangría y margen: el turno
        # se distingue por forma y posición, no solo por el color del rótulo.
        # El método también lo reaplica al cambiar de tema/zoom.
        self._configurar_tags_historial()

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
        self.pie = pie
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
            ("<F11>", self.toggle_foco),
            ("<Escape>", self.cancel_request),
            ("<Control-plus>", lambda: self._ajustar_zoom(es.ZOOM_STEP)),
            ("<Control-equal>", lambda: self._ajustar_zoom(es.ZOOM_STEP)),
            ("<Control-minus>", lambda: self._ajustar_zoom(-es.ZOOM_STEP)),
            ("<Control-0>", self._restablecer_zoom),
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
            """Ejecuta la acción asociada al atajo y traga el evento de teclado."""
            accion()
            return "break"
        return manejador

    def toggle_foco(self) -> None:
        """Modo foco: deja solo el artículo, sin barra ni pie (F11 para salir)."""
        if not self._foco_activo:
            self._foco_previo_asistente = self.asistente_visible
            self._foco_activo = True
            self.barra.pack_forget()
            self.pie.pack_forget()
            if self.asistente_visible:
                self.panes.forget(self.panel_asistente)
            self.status.set("Modo foco: solo el artículo (F11 para salir).")
            self.editor.focus_set()
        else:
            self._foco_activo = False
            # Re-empaquetar los tres en el orden original (barra, pie, panes):
            # olvidar también los panes evita que el packer deje las capas con
            # tamaño cero al restaurarlas después de un `pack_forget`.
            self.panes.pack_forget()
            self.barra.pack(fill="x")
            self.pie.pack(side="bottom", fill="x")
            self.panes.pack(fill="both", expand=True, padx=es.ESP["sm"],
                            pady=(0, es.ESP["xs"]))
            if self._foco_previo_asistente and not self.asistente_visible:
                self.panes.add(self.panel_asistente, weight=32)
            self._sincronizar_boton_panel()
            self.status.set("Modo foco desactivado.")

    def _sincronizar_boton_panel(self) -> None:
        """Mantiene el texto del botón coherente con la visibilidad del panel."""
        if self.asistente_visible:
            self.boton_panel.config(text="◧  Ocultar panel IA  (F6)")
        else:
            self.boton_panel.config(text="◨  Mostrar panel IA  (F6)")

    def _ajustar_zoom(self, delta: float) -> None:
        """Sube o baja el cuerpo tipográfico, acotado y reaplicando el tema."""
        nuevo = round(es.ZOOM + delta, 1)
        if nuevo < es.ZOOM_MIN or nuevo > es.ZOOM_MAX:
            return
        es.ZOOM = nuevo
        self._aplicar_escala()
        self.status.set(f"Zoom: {int(nuevo * 100)}%")

    def _restablecer_zoom(self) -> None:
        es.ZOOM = 1.0
        self._aplicar_escala()
        self.status.set("Zoom: 100%")

    def _aplicar_escala(self) -> None:
        """Reaplica el tema y las fuentes de los campos de texto tras cambiar el zoom."""
        self._theme()
        self.editor.configure(font=es.fuente(es.TIPO_LG))
        self.input.configure(font=es.fuente())
        self.history.configure(font=es.fuente())
        self.history.tag_configure("rotulo_usuario", font=es.fuente(es.TIPO_SM, negrita=True))
        self.history.tag_configure("rotulo_bot", font=es.fuente(es.TIPO_SM, negrita=True))
        self.history.tag_configure("nota", font=es.fuente(es.TIPO_SM))
        self.history.tag_configure("you", font=es.fuente(negrita=True))
        self.history.tag_configure("bot", font=es.fuente(negrita=True))

    def _refrescar_menu_recientes(self) -> None:
        """Repinta el submenú de recientes desde la lista en memoria."""
        self.menu_recientes.delete(0, "end")
        if not self.recent_paths:
            self.menu_recientes.add_command(label="(vacío)", state="disabled")
            return
        for ruta in self.recent_paths:
            # def anidado en vez de lambda: mypy no infiere el tipo del parámetro
            # por defecto de una lambda, y esta captura temprana de `ruta` evita
            # el clásico bug de late binding en bucles.
            def _abrir(ruta: str = ruta) -> None:
                self._abrir_reciente(ruta)
            self.menu_recientes.add_command(label=ruta, command=_abrir)
        self.menu_recientes.add_separator()
        self.menu_recientes.add_command(label="Limpiar recientes",
                                        command=self._limpiar_recientes)

    def _registrar_reciente(self, path: Path) -> None:
        """Añade una ruta al frente de recientes, sin duplicados y con tope."""
        ruta = str(path.resolve())
        if ruta in self.recent_paths:
            self.recent_paths.remove(ruta)
        self.recent_paths.insert(0, ruta)
        del self.recent_paths[10:]
        self._refrescar_menu_recientes()

    def _abrir_reciente(self, ruta: str) -> None:
        """Abre un documento reciente; lo retira si ya no existe."""
        path = Path(ruta)
        if not path.is_file():
            if ruta in self.recent_paths:
                self.recent_paths.remove(ruta)
                self._refrescar_menu_recientes()
            self.show_error("Documento no disponible",
                            f"{ruta}\n\nEl archivo ya no existe.")
            return
        self.load_document(path)

    def _limpiar_recientes(self) -> None:
        self.recent_paths = []
        self._refrescar_menu_recientes()
        self.status.set("Lista de recientes vaciada.")

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
            self.status.set("Asistente oculto. F6 lo vuelve a mostrar.")
            self.editor.focus_set()
        else:
            self.panes.add(self.panel_asistente, weight=32)
            self.status.set("Asistente visible.")
        self._sincronizar_boton_panel()

    @property
    def asistente_visible(self) -> bool:
        """True si el panel del asistente está visible."""
        # panes() devuelve rutas Tcl (cadenas), no objetos widget: comparar el
        # widget directamente daba siempre False y el panel nunca se ocultaba.
        return str(self.panel_asistente) in self.panes.panes()
    def copy_response(self):
        """Copia la última respuesta al portapapeles, si la hay."""
        if not self.scope.last_response:return
        self.clipboard_clear(); self.clipboard_append(self.scope.last_response); self.status.set("Última respuesta copiada.")
    @staticmethod
    def select_all_text(event) -> str:
        """Selecciona todo el texto del widget que recibió el evento."""
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
        """Menú contextual del historial: copiar y seleccionar."""
        menu=tk.Menu(self,tearoff=False,background=es.SUPERFICIE_ALTA,foreground=es.TEXTO,activebackground=es.ACENTO,activeforeground=es.ACENTO_TEXTO,font=es.fuente())
        menu.add_command(label="Copiar",command=lambda:self.history.event_generate("<<Copy>>"))
        menu.add_command(label="Copiar mensaje",command=lambda:self._copiar_mensaje(event))
        menu.add_command(label="Seleccionar todo",command=lambda:self.history.tag_add("sel","1.0","end-1c"))
        menu.tk_popup(event.x_root,event.y_root); menu.grab_release()
        return "break"

    def _copiar_mensaje(self, event) -> None:
        """Copia el mensaje que contiene al cursor (voz, cuerpo o nota)."""
        indice = f"@{event.x},{event.y}"
        for etiqueta in ("cuerpo_usuario", "cuerpo_bot", "nota"):
            rango = self.history.tag_prevrange(etiqueta, f"{indice}+1c")
            if not rango:
                continue
            inicio, final = rango
            if self.history.compare(indice, "<", inicio) or self.history.compare(indice, ">", final):
                continue
            texto = self.history.get(inicio, final).strip()
            if not texto:
                continue
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.status.set("Mensaje copiado.")
            return
        self.status.set("No hay mensaje aquí.")
    def modified(self,_=None):
        """Marca la sesión como sucia al editar el documento."""
        if not self.editor.edit_modified(): return
        self.editor.edit_modified(False)
        if self._suppress_modified: return  # Carga programática, no edición del usuario.
        self.session.dirty=True; self._sincronizar_estado_sync("dirty"); self.update_context(); self.schedule_stats(); self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        """Programa (o rearma) el respaldo de recuperación tras una edición."""
        if self.autosave_after is not None:
            self.after_cancel(self.autosave_after)
        self.autosave_after = self.after(AUTOSAVE_INTERVAL_MS, self._write_autosave)

    def _write_autosave(self) -> None:
        """Vuelca el editor al respaldo si sigue sucio; se rearma si hay que insistir."""
        self.autosave_after = None
        if self.closing:
            return
        if self.session.dirty and self.session.document_path is not None:
            try:
                write_autosave(self.session.document_path, self.editor.get("1.0", "end-1c"))
            except tk.TclError:
                return  # Ventana destruida mientras se volcaba.
            self._schedule_autosave()

    def _clear_current_autosave(self) -> None:
        if self.session.document_path is not None:
            clear_autosave(self.session.document_path)
        if self.autosave_after is not None:
            self.after_cancel(self.autosave_after)
            self.autosave_after = None

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
        """Reprograma la actualización de métricas del pie."""
        if self.stats_after: self.after_cancel(self.stats_after)
        self.stats_after=self.after(300,self.update_stats)
    def update_context(self):
        """Actualiza la etiqueta de contexto y el botón de revisión según la selección."""
        selected=self.editor.get("sel.first","sel.last").strip() if self.editor.tag_ranges("sel") else ""
        self.status.set(f"Contexto: selección de {len(selected.split())} palabras." if selected else "Contexto: artículo completo.")
        # Revisar solo lo seleccionado es deliberado (edición granular); el botón debe
        # decir sobre qué va a actuar en vez de prometer siempre el artículo entero.
        self.review_button.config(text="Revisar selección" if selected else "Revisar artículo")
        # La selección también cambia las métricas del pie: se refrescan junto al contexto.
        self.schedule_stats()
    def update_stats(self):
        """Reescribe las métricas del pie: palabras y tiempo de lectura."""
        self.stats_after=None
        total=len(self.editor.get("1.0","end-1c").split())
        seleccion=self.editor.get("sel.first","sel.last").strip() if self.editor.tag_ranges("sel") else ""
        palabras_sel=len(seleccion.split()) if seleccion else 0
        if total:
            lectura=max(1,round(total/220))
            if palabras_sel:
                self.editor_stats.config(text=f"{palabras_sel} de {total:,} palabras · {lectura} min de lectura")
            else:
                self.editor_stats.config(text=f"{total:,} palabras · {lectura} min de lectura")
        else:
            self.editor_stats.config(text="0 palabras · 0 min de lectura")
    def handle_callback_error(self, exc_type, exc_value, _traceback):
        """Manejador global de excepciones no controladas de Tkinter."""
        logger.exception("Excepción no controlada de Tkinter", exc_info=(exc_type, exc_value, _traceback))
        self.status.set("Ocurrió un error interno. Puedes continuar o reiniciar Articulador.")
        messagebox.showerror("Error interno",str(exc_value),parent=self)
    def show_error(self, title: str, detail: str) -> None:
        """Muestra un error en la barra de estado y en un diálogo modal."""
        self.status.set(title)
        messagebox.showerror(title, detail, parent=self)
    def load_document(self, path: Path) -> bool:
        """Sustituye el artículo activo y su conversación, cada una por documento."""
        success, error, session = self.docs.open_document(path)
        if not success:
            self.show_error("No se pudo abrir el documento", f"{path}\n\n{error}")
            return False
        documento = session.document_path
        if documento is None:
            self.show_error("No se pudo abrir el documento", f"{path}\n\nSin ruta de destino.")
            return False
        # Si se abandona otro documento, su respaldo de recuperación queda
        # obsoleto: el usuario ya decidió (guardó o descartó al salir).
        previous = self.session.document_path
        if previous is not None and previous != documento:
            clear_autosave(previous)
        # Recuperación ante cierre abrupto: si hay un respaldo distinto del
        # contenido en disco, se ofrece restaurarlo una sola vez y se resuelve.
        respaldo = read_autosave(documento)
        if respaldo is not None and respaldo != session.article:
            if messagebox.askyesno(
                "Recuperar respaldo",
                f"Hay un respaldo más reciente de «{path.name}» que no se llegó a "
                "guardar (quizá por un cierre inesperado).\n\n¿Restaurarlo?",
                parent=self,
            ):
                session.article = respaldo
            clear_autosave(documento)
        # La conversación es del documento, no de la sesión de trabajo: cada
        # artículo tiene su propia hebra. Al abandonar uno se guarda en memoria
        # lo que llevaba (se vuelca a disco al cerrar, en _guardar_estado_ui) y
        # se restaura la del documento que se abre, o queda vacía si es nuevo.
        if previous != documento:
            self._persistir_conversacion_en_memoria(previous)
            self.docs.set_session(session)
            self.session.conversation = self._restaurar_conversacion(documento)
            self._clear_history_widget()
            for item in self.session.conversation:
                self.append("Tú" if item.role == "user" else "Articulador", item.content)
        else:
            # Reabrir el mismo documento (p. ej. desde «Recientes»): el artículo
            # en disco se recarga, pero la conversación en curso no se toca.
            conversacion_en_curso = list(self.session.conversation)
            self.docs.set_session(session)
            self.session.conversation = conversacion_en_curso
        self._enter_document_scope(session.document_path)
        self._replace_editor_text(session.article)
        self.append("Articulador", f"Artículo activo: «{path.name}». La conversación y los artículos "
                    "de contexto se conservan para continuar el trabajo.",
                    es_respuesta=False)
        self._registrar_reciente(path)
        self.session.dirty=False; self._sincronizar_estado_sync("clean")
        self.update_context(); self.schedule_stats(); self.status.set(f"Documento abierto: {path.name}")
        return True

    def _clear_history_widget(self) -> None:
        """Vacía el panel de conversación (el estado ya vive en la sesión)."""
        self.history.config(state="normal")
        self.history.delete("1.0", "end")
        self.history.config(state="disabled")
    def send_message(self):
        """Envía el mensaje del cuadro de entrada como consulta normal."""
        message=self.input.get("1.0","end-1c").strip()
        if not message or self.session.request_active:return
        # Validar ANTES de pintar el turno: sin perfil/key el mensaje quedaría
        # como un turno fantasma del usuario que nunca recibe respuesta.
        if not self.profile.enabled or not self.key:
            self.append("Articulador","Configura un perfil LLM y una key para responder.")
            return
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
            """Transmite la revisión en segundo plano y publica eventos de UI."""
            self.llm.stream_response(
                profile, api_key, texto, "", conversacion,
                on_chunk=lambda chunk: self.chunks.append(request_id, chunk),
                on_error=lambda error: self.control_queue.put_nowait(("error", request_id, f"No pude responder: {error}", [])),
                on_complete=lambda result, usage: self.control_queue.put_nowait(("complete", request_id, result, [], usage, "review")),
                request_id=request_id,
                cancel_event=cancel_event,
            )
        hilo = threading.Thread(target=work, daemon=True)
        self._worker_threads.append(hilo)
        hilo.start()

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
        packet, files = self._reference_packet()
        self.confirm_and_send(request_id, message, selected, packet, files, cancel_event)

    def _reference_packet(self) -> tuple[str, list[str]]:
        """Construye el paquete desde instantáneas elegidas explícitamente.

        Cada artículo se congela al añadirlo. Así, abrir otro documento no hace
        desaparecer el anterior ni sustituye su contenido por el del disco.
        """
        remaining = min(self.profile.max_context_chars // 3, MAX_CONTEXT_PACKET_CHARS)
        parts: list[str] = []
        files: list[str] = []
        for article in self.context_articles:
            if remaining <= 0:
                break
            excerpt = article.content[:min(MAX_CONTEXT_EXCERPT_CHARS, remaining)]
            if not excerpt:
                continue
            parts.append(f"ARTÍCULO DE CONTEXTO: {article.label}\n---\n{excerpt}")
            files.append(article.label)
            remaining -= len(excerpt)
        return "\n\n".join(parts), files

    def confirm_and_send(self, request_id, message, selected, packet, files, cancel_event):
        """Confirma la privacidad del contexto y lanza el envío en un hilo."""
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types or cancel_event.is_set(): return

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
        contexto_extra = " + ".join(files)
        detail=f"Contexto: artículo activo{(' + ' + contexto_extra) if contexto_extra else ''} · ~{input_tokens:,} tokens entrada"
        if cost: detail+=f" · coste máx. ~${cost:.4f}"
        self.cost_label.set(detail)
        # Lo que el usuario aprueba son los FRAGMENTOS locales: la huella cubre el
        # paquete de contexto, no el artículo ni la conversación. Con el prompt
        # completo el hash cambiaba en cada mensaje y el diálogo salía siempre.
        key = self.approved_contexts.key_for(profile, packet, files)

        def lanzar() -> None:
            """Arranca el envío de la petición ya confirmada."""
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
            """Ejecuta la petición HTTP en un hilo daemon y publica eventos de UI."""
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
        hilo = threading.Thread(target=work, daemon=True)
        self._worker_threads.append(hilo)
        hilo.start()

    def _pedir_aprobacion(self, request_id: int, files: list[str],
                          key: ContextApprovalKey, al_aceptar) -> None:
        """Muestra la confirmación de contexto dentro del panel del asistente."""
        self.aprobacion_texto.set(
            "Se enviará el artículo activo de la izquierda y "
            f"{len(files)} artículo(s) de contexto al proveedor: "
            + ", ".join(files)
        )
        self.set_estado(EstadoUI.PREPARANDO, "esperando tu confirmación")

        def aceptar() -> None:
            """Acepta la autorización del contexto y lanza el envío."""
            self._ocultar_aprobacion()
            # Desalojar la aprobación más antigua, no las 128: vaciar el conjunto
            # entero obligaba a reconfirmar todo de golpe.
            self.approved_contexts.remember(key)
            al_aceptar()

        def rechazar() -> None:
            """Rechaza la autorización y aborta la petición."""
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
        """Cierra una petición: vuelca resultado o error según su tipo."""
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
        """Pinta un fragmento incremental de la respuesta en curso."""
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
        """Cancela la petición en curso desde el botón Cancelar o la tecla Escape."""
        if not self.session.request_active:
            return
        self._cancel_active_request()
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
                    self._ui_events_after = self.after(50, self.process_ui_events)
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
        """Abre el diálogo de hallazgos de una revisión (una sola ventana a la vez)."""
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
        """Deshace el último ajuste de revisión, si pertenece al documento actual."""
        if not self.scope.review_before:return
        # El deshacer solo es válido sobre el documento del que se tomó la instantánea:
        # sin esta comprobación volcaba el artículo anterior sobre el actual y lo
        # marcaba como sucio, a un Ctrl+S de destruirlo.
        if not self.scope.owns(self.session.document_path):
            self.scope.review_before=""
            self.status.set("El ajuste a deshacer pertenece a otro documento."); return
        self.editor.delete("1.0","end"); self.editor.insert("1.0",self.scope.review_before); self.scope.review_before=""; self.session.dirty=True; self.status.set("Último ajuste de revisión deshecho.")
    def open_document(self):
        """Pide un archivo al usuario y abre el documento con las confirmaciones previas."""
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
            next_path = Path(path).resolve()
            current_text = self.editor.get("1.0", "end-1c")
            current_path = self.session.document_path
            if (current_text.strip() and current_path != next_path
                    and messagebox.askyesno(
                        "Conservar y autorizar contexto",
                        "Vas a abrir otro artículo.\n\n"
                        "¿Quieres conservar el artículo actual y autorizar su envío a "
                        f"{self.profile.provider}/{self.profile.model} durante esta sesión?\n\n"
                        "Podrás quitarlo después en «Contexto de artículos».",
                        parent=self,
                    )):
                self._add_current_article_to_context()
                self._authorize_context_articles()
            # La lectura y el manejo de errores viven en DocumentManager: aquí solo
            # se decide qué archivo abrir.
            self.load_document(next_path)

    def _update_references_button(self) -> None:
        count = len(self.context_articles)
        label = "artículo" if count == 1 else "artículos"
        self.references_button.config(text=f"Contexto: {count} {label}")

    def _upsert_context_article(self, article: ContextArticle) -> bool:
        """Añade o actualiza una instantánea, sin duplicarla en el contexto."""
        for index, existing in enumerate(self.context_articles):
            if existing.source_id == article.source_id:
                self.context_articles[index] = article
                self._update_references_button()
                return False
        self.context_articles.append(article)
        self._update_references_button()
        return True

    def _add_current_article_to_context(self) -> bool:
        """Guarda el texto visible como contexto antes de abrir o editar otro."""
        content = self.editor.get("1.0", "end-1c")
        if not content.strip():
            return False
        path = self.session.document_path
        label = path.name if path else "Artículo sin guardar"
        source_id = f"article:{path.resolve()}" if path else "article:sin-ruta"
        return self._upsert_context_article(ContextArticle(source_id, label, content))

    def _authorize_context_articles(self) -> None:
        """Autoriza el conjunto actual para el destinatario activo, una sola vez."""
        packet, files = self._reference_packet()
        self.approved_contexts.remember_for(self.profile, packet, files)

    def _ask_to_authorize_articles(self, labels: list[str], parent) -> bool:
        """La autorización ocurre al añadir contexto, nunca al enviar después."""
        if not labels:
            return False
        return messagebox.askyesno(
            "Autorizar artículos de contexto",
            "Se conservarán y podrán enviarse a "
            f"{self.profile.provider}/{self.profile.model} durante esta sesión:\n\n"
            + ", ".join(labels),
            parent=parent,
        )

    def _add_references(self, paths: tuple[str, ...] | list[str]) -> int:
        """Añade instantáneas de archivos de contexto sin alterar el editor."""
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
                    content = source.read(MAX_INDEXED_FILE_BYTES).decode("utf-8", errors="replace")
            except OSError:
                continue
            if self._upsert_context_article(ContextArticle(f"article:{path}", path.name, content)):
                added += 1
        return added

    def manage_references(self) -> None:
        """Permite conservar artículos previos al cambiar el artículo activo."""
        dialog = tk.Toplevel(self)
        dialog.title("Contexto de artículos")
        dialog.transient(self)
        dialog.configure(bg=es.SUPERFICIE)
        dialog.minsize(460, 280)
        dialog.geometry("580x360")
        frame = ttk.Frame(dialog, style="Superficie.TFrame", padding=es.ESP["lg"])
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Artículos de contexto", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(frame, text=("El artículo de la izquierda es el activo. Añade aquí artículos previos (.md o .txt): "
                               "se conservan al abrir otro artículo y se autorizan al añadirlos."),
                  style="TenueSuperficie.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(es.ESP["xs"], es.ESP["sm"]))
        # La fila de acciones se reserva ANTES de la lista expansible: con pack,
        # lo colocado después es lo que se recorta al estrechar la ventana.
        actions = ttk.Frame(frame, style="Superficie.TFrame")
        actions.pack(side="bottom", fill="x", pady=(es.ESP["lg"], 0))
        entries = tk.Listbox(frame, selectmode="extended", exportselection=False,
                             background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                             selectbackground=es.SELECCION, selectforeground=es.TEXTO,
                             relief="flat", highlightthickness=1,
                             highlightbackground=es.BORDE, highlightcolor=es.FOCO,
                             borderwidth=0, font=es.fuente(), activestyle="none")
        entries.pack(fill="both", expand=True)

        def refresh() -> None:
            """Recarga la lista de artículos de contexto desde la sesión."""
            entries.delete(0, "end")
            for article in self.context_articles:
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
            if not self._ask_to_authorize_articles(labels, dialog):
                return
            count = self._add_references(selected_paths)
            self._authorize_context_articles()
            refresh()
            if count:
                self.status.set(f"{count} artículo(s) añadido(s) al contexto.")

        def remove() -> None:
            """Elimina los artículos de contexto seleccionados en la lista."""
            selected = list(entries.curselection())
            if not selected:
                return
            self.context_articles = [article for index, article in enumerate(self.context_articles)
                                     if index not in selected]
            self._update_references_button()
            refresh()
            self.status.set("Contexto de artículos actualizado.")

        # Acción primaria a la derecha, como en el resto de diálogos.
        def add_current() -> None:
            """Añade el artículo activo como contexto."""
            path = self.session.document_path
            label = path.name if path else "Artículo sin guardar"
            if not self._ask_to_authorize_articles([label], dialog):
                return
            added = self._add_current_article_to_context()
            self._authorize_context_articles()
            refresh()
            self.status.set("Artículo activo añadido al contexto." if added
                            else "Artículo activo actualizado en el contexto.")

        ttk.Button(actions, text="Añadir artículos…", style="Primaria.TButton",
                   command=add).pack(side="right")
        ttk.Button(actions, text="Quitar seleccionadas", command=remove).pack(
            side="right", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Añadir artículo activo", command=add_current).pack(
            side="left", padx=(0, es.ESP["sm"]))
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="left")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        refresh()
        self._registrar_reaplicar_tema(dialog,
                                       lambda: self._reaplicar_tema_contexto(dialog, entries))
        entries.focus_set()

    def _reaplicar_tema_contexto(self, dialog: tk.Toplevel, entries: tk.Listbox) -> None:
        """Repinta el diálogo de contexto al cambiar de tema, sin perder la lista."""
        dialog.configure(bg=es.SUPERFICIE)
        entries.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                          selectbackground=es.SELECCION, selectforeground=es.TEXTO,
                          highlightbackground=es.BORDE, highlightcolor=es.FOCO)

    def save_document(self, save_as: bool = False)->bool:
        """Guarda el artículo en su ruta, o pide destino si no la tiene."""
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
        self._sincronizar_estado_sync("saved")
        self.status.set("Artículo guardado.")
        return True
    def save_project(self):
        """Guarda el proyecto recuperable (artículo + conversación) en un JSON."""
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
        """Abre un proyecto y restaura el artículo y su conversación."""
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
        self.session.dirty=False; self._sincronizar_estado_sync("clean")
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
        """Abre el diálogo de configuración de perfiles LLM."""
        show_settings_dialog(self)

    def _cancel_active_request(self):
        """Baja la petición viva y devuelve la interfaz al reposo.

        Punto único de cancelación: lo usan el botón Cancelar, la tecla Escape
        y los cambios de documento/proyecto. Antes había dos copias casi
        idénticas (`cancel_request` y `_cancel_active_request`) que ya habían
        empezado a divergir: una marcaba el estado CANCELADO y ocultaba la barra
        de aprobación, la otra no. Reunirlas aquí evita ese desdoblamiento.
        """
        if self.cancel_event:
            self.cancel_event.set()
        # Cancelar en LLMClient (generation_counter es el request_id actual).
        self.llm.cancel(self.generation_counter)
        # Limpiar TODOS los buffers pendientes: una respuesta tardía no debe
        # pintarse ni reactivar una petición ya cerrada.
        self.request_types.clear()
        self.chunks.clear()
        self.streaming_request = None
        self.streaming_text = ""
        self.session.request_active = False
        self._reset_request_ui()
        # Si se canceló mientras se esperaba la confirmación de contexto, la
        # barra de aprobación queda huérfana y hay que retirarla.
        self._ocultar_aprobacion()

    def close(self):
        """Cierra la aplicación de forma limpia: confirma, cancela y persiste."""
        if self.session.dirty and not messagebox.askyesno("Cambios sin guardar","¿Cerrar sin guardar?"):return
        self.closing=True
        # Cancelar cualquier solicitud activa
        if self.session.request_active:
            self._cancel_active_request()
        # Persistir el estado de interfaz (geometría, zoom, recientes y conversación).
        self._guardar_estado_ui()
        # Cierre limpio: la decisión ya está tomada, el respaldo de recuperación
        # no debe resucitar cambios descartados en la próxima apertura.
        self._clear_current_autosave()
        self.destroy()

    def _restaurar_conversacion(self, path: Path | None) -> list[ChatMessage]:
        """Recupera la conversación persistida de un documento, si existe."""
        return ui_state.restaurar_conversacion(self.ui_state.get("conversations"), path)

    def _persistir_conversacion_en_memoria(self, path: Path | None) -> None:
        """Vuelca la conversación activa al estado en memoria, bajo la clave del documento.

        No toca disco (eso ocurre en `_guardar_estado_ui`, al cerrar). Se llama
        al abandonar un documento por otro, para no perder sus turnos aunque la
        sesión siga abierta; y de nuevo al cerrar, para capturar el documento
        que queda activo en ese momento.
        """
        if path is None:
            return
        self.ui_state["conversations"] = ui_state.persistir_conversacion(
            self.ui_state.get("conversations"), path, self.session.conversation
        )

    def _podar_conversaciones(self, conversaciones: dict) -> dict:
        """Descarta conversaciones de documentos que ya no están vigentes.

        Vigente = sigue en «recientes» o es el documento activo. Sin esto,
        `estado.json` acumula para siempre una entrada por cada artículo que se
        abrió alguna vez, aunque ya no exista o el usuario lo haya limpiado de
        recientes.
        """
        vigentes = set(self.recent_paths)
        if self.session.document_path is not None:
            vigentes.add(str(self.session.document_path))
        return ui_state.podar_conversaciones(conversaciones, vigentes)

    def _snapshot_estado_ui(self) -> dict:
        """Instantánea completa del estado de interfaz con los valores vivos.

        Geometría, visibilidad del panel, zoom, tema, recientes y conversaciones
        se leen de la ventana y de la sesión en el momento de escribir, nunca de
        una copia congelada. Es la única forma de construir lo que llega a
        `estado.json`: la usa tanto el cierre (`_guardar_estado_ui`) como la
        persistencia inmediata del tema (`_guardar_preferencia_tema`), de modo
        que el tema nunca pisa el resto de preferencias.
        """
        estado = dict(self.ui_state)
        estado["geometry"] = self.geometry()
        estado["panel_visible"] = self.asistente_visible
        estado["zoom"] = es.ZOOM
        estado["theme"] = self.theme
        estado["recent"] = self.recent_paths
        conversaciones = estado.get("conversations", {})
        if not isinstance(conversaciones, dict):
            conversaciones = {}
        estado["conversations"] = self._podar_conversaciones(conversaciones)
        return estado

    def _guardar_preferencia_tema(self) -> None:
        """Persiste el tema de inmediato, de forma atómica y defensiva.

        Se llama desde `_aplicar_tema` en cada cambio: la preferencia sobrevive a
        una terminación abrupta sin esperar al cierre de la aplicación. Escribe la
        instantánea completa (nunca solo la clave `theme`, para no pisar el resto
        de preferencias) con la escritura atómica de `storage`. Un fallo de
        escritura se registra y se ignora: el cambio visual ya está aplicado y no
        se revierte.
        """
        try:
            self.ui_state["theme"] = self.theme
            storage.save_ui_state(self._snapshot_estado_ui(), self.config_path)
        except Exception:
            logger.warning("No se pudo guardar la preferencia de tema", exc_info=True)

    def _guardar_estado_ui(self) -> None:
        """Vuelca el estado de interfaz al disco; best-effort, nunca rompe el cierre."""
        try:
            self._persistir_conversacion_en_memoria(self.session.document_path)
            storage.save_ui_state(self._snapshot_estado_ui(), self.config_path)
        except Exception:
            logger.warning("No se pudo guardar el estado de interfaz", exc_info=True)

    def destroy(self) -> None:
        """Cancela los callbacks `after` pendientes antes de destruir la ventana.

        Sin esto, los temporizadores ya programados (`process_ui_events`, el
        autosave y las estadísticas) disparaban tras el cierre contra una Tcl
        destruida, dejando ruido «invalid command name» en la consola.
        """
        self.closing = True
        for after_id in (self._ui_events_after, self.autosave_after, self.stats_after):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._esperar_hilos_de_peticion()
        super().destroy()

    def _esperar_hilos_de_peticion(self, timeout: float = 2.0) -> None:
        """Da a los hilos de review/request una última oportunidad de terminar.

        `close()` ya cancela la petición activa (cancel_event) antes de llegar
        aquí, pero la cancelación es cooperativa: el hilo tarda un momento en
        notarla. Sin esta espera, un hilo que aún no había ni empezado a
        ejecutarse podía sobrevivir a la ventana de Tk ya destruida y chocar
        con Tcl desde otro hilo al ejecutarse. El tope es total, no por hilo,
        para no alargar el cierre por una petición realmente colgada: si no
        terminan a tiempo, siguen como daemon y el proceso no se bloquea por
        ellos, solo se registra el aviso.
        """
        limite = time.monotonic() + timeout
        for hilo in self._worker_threads:
            restante = limite - time.monotonic()
            if restante <= 0:
                break
            hilo.join(timeout=restante)
        vivos = [hilo for hilo in self._worker_threads if hilo.is_alive()]
        if vivos:
            logger.warning("%d hilo(s) de petición seguían activos al cerrar", len(vivos))
