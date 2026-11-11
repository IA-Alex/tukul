from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from tukul_core import storage
from tukul_core.autosave import clear_autosave, read_autosave, write_autosave
from tukul_core.config_validator import validate_startup_config

# Re-exportados para los consumidores y tests que aún los parchean/importan
# desde `tukul_ui.app`, aunque el pipeline vive ya en `tukul_ui.ideas`.
from tukul_core.impact_analyzer import CorrelationEngine, IdeaGenerator  # noqa: F401
from tukul_core.llm import SYSTEM_PROMPT, estimate_prompt_tokens
from tukul_core.logging_config import setup_logging
from tukul_core.models import (
    ArticleIdea,
    ArticleSession,
    ChatMessage,
    CorrelationGroup,
    FeedEntry,
    LlmProfile,
)
from tukul_core.prompting import REVIEW_PROMPT, build_editor_prompt, build_review_prompt
from tukul_core.real_time_feed import FeedOrchestrator  # noqa: F401
from tukul_core.review import diagnose_findings, parse_findings, respuesta_fuera_de_rol

# Re-exportados para los tests y consumidores que aún los parchean/importan
# desde `tukul_ui.app`, aunque el fetch vive ya en `tukul_ui.contexto_dialogo`.
from tukul_core.threat_feed import ThreatFeedError, build_threat_context  # noqa: F401
from tukul_ui import contexto, ui_state, ventana
from tukul_ui import estilo as es
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.components.assistant_panel import AssistantPanel
from tukul_ui.components.editor_panel import EditorPanel
from tukul_ui.components.top_bar import TopBar
from tukul_ui.context_approval import ContextApprovalCache, ContextApprovalKey
from tukul_ui.contexto_dialogo import ContextController
from tukul_ui.dialogs import show_review_dialog, show_settings_dialog
from tukul_ui.document_manager import DocumentManager
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import ESTADOS_ACTIVOS, EstadoUI
from tukul_ui.ideas import IdeasController
from tukul_ui.llm_session_manager import LLMSessionManager
from tukul_ui.request_lifecycle import RequestLifecycle
from tukul_ui.tema import aplicar_estilos
from tukul_ui.worker_threads import WorkerThreads

# Límites del paquete de artículos de contexto que acompaña al artículo activo.
# Vivían en tukul_core/context.py junto al índice BM25; al retirar ese
# índice, las constantes se quedaron aquí, donde se usan de verdad.
MAX_CONTEXT_PACKET_CHARS = 12_000
MAX_CONTEXT_EXCERPT_CHARS = 3_000
# El resumen de amenazas es un texto curado y determinista (no un archivo
# arbitrario del usuario), así que se le da más margen dentro del mismo tope de
# paquete. El límite global de tokens en `confirm_and_send` sigue siendo la
# barrera fail-closed real.
MAX_THREAT_FEED_EXCERPT_CHARS = 10_000
MAX_INDEXED_FILE_BYTES = 50_000
# Tope de espera al resolver la key del llavero antes de enviar. Con un llavero
# sano la lectura tarda milisegundos; el tope evita que una interfaz rota
# (D-Bus sin respuesta) deje el envío colgado indefinidamente.
KEYRING_TIMEOUT_SECONDS = 3.0
# Ventana temporal de la fuente de amenazas (CVE recientes). El fetch nunca es
# automático: solo se dispara desde el diálogo de contexto, por acción del
# usuario, igual que añadir un artículo de contexto.
THREAT_FEED_HOURS = 24
THREAT_FEED_SOURCE_ID = "threat-feed:cve-recientes"
# Caché local de entradas de fuentes oficiales para evitar consultas repetidas.
FEED_CACHE_DIR = Path.home() / ".local" / "state" / "tukul" / "feed_cache"
# Frecuencia del respaldo de recuperación: se escribe solo cuando hay cambios.
AUTOSAVE_INTERVAL_MS = 5000

# Tamaño mínimo de la ventana. El ancho no es una preferencia estética: por
# debajo de ~1100 px la barra superior no cabe (acciones + documento + estado +
# configuración) y el nombre del artículo empezaba a desaparecer, que es justo
# el dato que el usuario necesita para saber qué está editando. 1120 deja un
# margen de 8 px sobre los 1112 que pide la barra con «Sin artículo abierto».
# Viven en `tukul_ui.ventana` (junto a la lógica que los usa) y se re-exportan
# aquí para no romper a quien los importe desde `app`.
ANCHO_MINIMO_VENTANA = ventana.ANCHO_MINIMO_VENTANA
ALTO_MINIMO_VENTANA = ventana.ALTO_MINIMO_VENTANA


def _aplicar_estado_ttk(widget: Any, disponible: bool) -> None:
    """Habilita o inhabita un widget ttk aceptando estados ya resueltos.

    `state(...)` de ttk es acumulativo y solo entiende modificadores
    (`!disabled`). Los dobles de prueba pueden devolver y registrar el juego
    resuelto (`disabled` / `""`): si `disabled` ya está presente, solo ese
    modificador obtiene el resultado pedido.
    """
    try:
        # `widget.state()` sin argumentos solo existe en ttk; un objeto que no
        # lo exponga se trata como widget ajeno y la llamada debe fallar.
        actual = list(widget.state())
    except (tk.TclError, AttributeError, TypeError):
        # Sin lectura de estado (doble de prueba): se aplica el cambio igual;
        # repetirlo es inocuo en ttk y mantiene observable el contrato.
        actual = ["disabled"] if disponible else [""]
    if not all(isinstance(item, str) for item in actual):
        return
    desactivado = "disabled" in actual
    if desactivado == (not disponible):
        return
    try:
        widget.state(["!disabled"] if disponible else ["disabled"])
    except (tk.TclError, AttributeError, TypeError):
        pass


def _vestir_cancelar(boton: Any, activo: bool) -> None:
    """«Cancelar» cambia de traje, no de sitio.

    Visible siempre para que la salida se descubra antes de necesitarla. En
    reposo usa el estilo «Inactivo» (sin relieve ni borde): se lee como «aquí
    no hay nada que cancelar», no como un control roto junto a «Revisar
    artículo». Con una consulta viva recupera el botón normal.
    """
    estilo = "TButton" if activo else "Inactivo.TButton"
    try:
        if str(boton.cget("style")) != estilo:
            boton.configure(style=estilo)
    except (tk.TclError, AttributeError, TypeError):
        pass


def _widget_propio(dueno: object, nombre: str) -> Any:
    """Atributo de la instancia sin `getattr` (Tk delega los ausentes en Tcl).

    En un `tk.Tk`, `getattr` de un atributo AUSENTE delega en el intérprete
    Tcl y puede terminar en recursión infinita en raíces sintéticas o a medio
    construir. Solo se consulta el diccionario de la instancia, y se admite el
    valor si de verdad existe como atributo propio.
    """
    try:
        return dueno.__dict__.get(nombre)
    except AttributeError:
        return None


# `ContextArticle` vive en `tukul_ui.contexto` (módulo neutral, sin la ventana)
# para que el controlador de ideas pueda importarlo sin ciclos. Se re-exporta
# aquí: `from tukul_ui.app import ContextArticle` sigue funcionando.
ContextArticle = contexto.ContextArticle

logger = setup_logging()


def _en_el_hilo_de_tk(raiz: tk.Misc) -> bool:
    """True si el llamador es el hilo que puede tocar Tcl.

    `after()` desde un worker lanza `RuntimeError: main thread is not in main
    loop` en CPython 3.13, y ese error —surgido durante la recolección de
    basura— puede abortar el proceso entero en lugar de propagarse. Los
    workers son daemon: pueden sobrevivir al cierre y llegar aquí. Mejor no
    programar nada que morir.
    """
    return threading.current_thread() is threading.main_thread()


class TukulApp(tk.Tk):
    """Ventana principal: widgets, estado, streaming y ciclo de vida de la sesión."""

    def __init__(self, config_path: Path = storage.CONFIG_PATH) -> None:
        super().__init__()
        # Widgets de acción que la sincronización de estados consulta antes de
        # que `_build` los cree (y que los ayudantes sin ventana sustituyen).
        self.send_button: Any = None
        self.review_button: Any = None
        self.cancel_button: Any = None
        self.cost_label: Any = None
        self.barra: Any = None
        self._coste_reservado = False
        self.title("Tukul")
        # Interruptor maestro del estilo visual de la aplicación: `ttk.Style`
        # sin él usa el tema nativo (clam/alt), que ignora los estilos definidos
        # en `_theme` y reintroduce el degradado gris de Tk en botones como
        # «Guardar» o «Enviar». Debe fijarse antes de crear estilos.
        try:
            ttk.Style(self).theme_use("clam")
        except tk.TclError:
            # Tema nativo ausente: se conserva el de Tk y `_theme` reintenta.
            pass
        self._ajustar_dpi()
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
        # Caché del llavero y perfiles cuya lectura ya está en curso. El llavero
        # se consulta en un hilo daemon; aquí solo viven los resultados.
        self._keys_llavero: dict[str, str] = {}
        self._llaves_en_curso: dict[str, threading.Event] = {}

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
        """API key en vigor: variable de entorno > key de sesión > llavero.

        El llavero puede tardar (D-Bus/Secret Service en Linux, diálogo de
        acceso en macOS): leerlo en el hilo de Tk congelaba la ventana en cada
        acceso. La lectura se mueve al hilo de trabajo y el resultado se cachea;
        aquí solo se sirve lo ya conocido, sin bloquear.
        """
        return (os.environ.get(self.profile.api_key_env)
                or self.session_keys.get(self.active_profile, "")
                or self._keys_llavero.get(self.active_profile, ""))

    def _prime_key(self) -> str:
        """Lanza la lectura del llavero del perfil activo y devuelve lo cacheado.

        No bloquea: la interfaz llama a esto al cambiar de perfil y el valor
        llega al mapa en cuanto el hilo de lectura termina.
        """
        perfil = self.active_profile
        if perfil not in self._keys_llavero and perfil not in self._llaves_en_curso:
            self._precargar_key(perfil)
        return self.key

    def _precargar_key(self, perfil: str) -> None:
        """Lanza la lectura del llavero en un hilo daemon y guarda el resultado.

        Usa `threading.Event` como futuro: quien pueda bloquear (un worker)
        espera con `_esperar_key`; la interfaz solo consulta la caché.
        """
        # Sin backend de sistema no se lanza el hilo: en CI/contenedor la
        # lectura puede abortar el proceso en lugar de devolver un error.
        if not storage.credential_backend_disponible():
            self._keys_llavero[perfil] = ""
            return
        listo = threading.Event()
        self._llaves_en_curso[perfil] = listo

        def leer() -> None:
            try:
                valor = storage.load_key(perfil)
            except storage.KeyringUnavailableError:
                # El llavero existe pero no responde: NO es «no hay key». Se
                # cachea vacío para no reintentar en bucle, pero se avisa en la
                # barra; si no, el usuario leería «Configura una key», pista falsa.
                self.control_queue.put_nowait(("keyring_unavailable", perfil))
                valor = ""
            except Exception:
                # Un llavero ajeno (D-Bus, backend del SO) no debe romper la UI.
                valor = ""
            self._keys_llavero[perfil] = valor
            # Marcar antes de publicar: quien espera esa misma señal no debe
            # encontrar todavía su entrada en `_llaves_en_curso` ni un instante.
            self._llaves_en_curso.pop(perfil, None)
            listo.set()

        threading.Thread(target=leer, name=f"keyring-{perfil}", daemon=True).start()

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

    def _ajustar_dpi(self) -> None:
        """Declara la aplicación «DPI-aware» y calibra la escala de Tk.

        Sin esto, en Windows con escalado al 150-200 % el sistema reescala una
        ventana dibujada a 96 DPI: texto borroso y controles de tamaño
        incorrecto. En X11 se consulta el DPI del servidor para que `tk scaling`
        coincida con la pantalla real. Todo es best-effort: sondeos de entornos
        sin el módulo, sin soporte o con servidores que ya lo resuelven.
        """
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except (ImportError, AttributeError, OSError):
            pass
        try:
            pulgadas = float(self.winfo_fpixels("1i"))
            if pulgadas > 0:
                self.tk.call("tk", "scaling", pulgadas / 72.0)
        except (tk.TclError, ValueError):
            pass
        # La familia tipográfica se resuelve con la raíz ya viva.
        try:
            from tkinter import font as tkfont

            es.resolver_familia(tkfont.families(self))
        except tk.TclError:
            pass

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
            self.minsize(min(ANCHO_MINIMO_VENTANA, ancho), min(ALTO_MINIMO_VENTANA, alto))
            self.geometry(f"{ancho}x{alto}")
        else:
            self.minsize(ANCHO_MINIMO_VENTANA, ALTO_MINIMO_VENTANA)
            self.geometry("1180x760")

    def _ventana_mapeada(self) -> bool:
        """¿La ventana ya tiene tamaño y posición reales?

        Antes de `update_idletasks`, `geometry()` devuelve el tamaño pedido
        (a menudo «1x1+0+0»), no el real. Persistir ese valor convertiría una
        ventana que aún no se pintó en una miniatura de 1120x540 al reabrir.
        """
        try:
            return bool(self.winfo_ismapped() and self.winfo_width() > 1
                        and self.winfo_height() > 1)
        except tk.TclError:
            return False

    # La lógica de saneado vive en `tukul_ui.ventana` (funciones puras, probadas
    # sin montar la ventana). Estas delegaciones conservan la API histórica de
    # `TukulApp` para no romper a los consumidores ni a los tests existentes.
    PATRON_GEOMETRIA = ventana.PATRON_GEOMETRIA

    @classmethod
    def _geometria_saneada(cls, guardada: object, pantalla_ancho: int,
                           pantalla_alto: int) -> str | None:
        """Delega en `ventana.geometria_saneada` (ver ahí las reglas)."""
        return ventana.geometria_saneada(guardada, pantalla_ancho, pantalla_alto)

    @staticmethod
    def _zoom_validado(valor: object) -> float:
        """Delega en `ventana.zoom_validado`."""
        return ventana.zoom_validado(valor)

    @staticmethod
    def _recientes_validados(valor: object) -> list[str]:
        """Delega en `ventana.recientes_validados`."""
        return ventana.recientes_validados(valor)

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

        ancho, alto = self.winfo_screenwidth(), self.winfo_screenheight()
        if ancho <= 100 or alto <= 100:
            return
        saneada = self._geometria_saneada(guardada, ancho, alto)
        if saneada is not None:
            self.geometry(saneada)

    @staticmethod
    def _tema_validado(valor: object) -> str:
        """Convierte el tema persistido a uno válido; 'dark' ante basura."""
        return es.tema_validado(valor)

    def _theme(self) -> None:
        """Aplica el sistema visual del tema activo: un fondo, dos superficies.

        Los estilos ttk se repintan en bloque (`tukul_ui.tema`); los widgets Tk
        con colores directos se reconfiguran en `_reaplicar_estilos_widgets` sin
        destruir ni recrear nada.
        """
        aplicar_estilos(self, self.theme, self._reaplicar_estilos_widgets)
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
        """Mantiene el botón coherente: la etiqueta anuncia la acción, no el color.

        La barra es la dueña del texto y del tooltip (así no hay dos fuentes de
        verdad); aquí solo se le pide que se adapte al tema nuevo.
        """
        barra = getattr(self, "barra", None)
        if barra is None:
            return
        try:
            barra.actualizar_estado(self.theme)
        except (tk.TclError, AttributeError):
            return

    def _sincronizar_estado_sync(self, estado: str) -> None:
        """Rótulo del documento: símbolo + texto + color, nunca solo color."""
        self._sync_estado = estado
        if estado == "dirty":
            texto, color = "●  Cambios sin guardar", es.ESTADO_AVISO
        elif estado == "saved":
            texto, color = "✓  Guardado", es.ESTADO_EXITO
        else:
            texto, color = "◌  Sin cambios", es.TEXTO_TENUE
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
            # Preservar el color tenue si el placeholder está activo
            input_fg = es.TEXTO_TENUE if self._placeholder_activo else es.TEXTO
            self.input.configure(background=es.SUPERFICIE_ALTA, foreground=input_fg,
                                 insertbackground=es.ACENTO, selectbackground=es.SELECCION,
                                 highlightbackground=es.SUPERFICIE_ALTA, highlightcolor=es.FOCO)
        if getattr(self, "history", None) is not None and self.history.winfo_exists():
            self.history.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                                   insertbackground=es.ACENTO, selectbackground=es.SELECCION,
                                   highlightbackground=es.SUPERFICIE, highlightcolor=es.FOCO)
            self._configurar_tags_historial()
        # Etiqueta de aprobación de contexto: colores directos sobre ttk.Label.
        # Vive en AssistantPanel, no directamente en TukulApp.
        panel = getattr(self, "panel_asistente", None)
        if panel is not None and getattr(panel, "aprobacion_label", None) is not None:
            try:
                if panel.aprobacion_label.winfo_exists():
                    panel.aprobacion_label.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO)
            except tk.TclError:
                pass
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
        # Contrapartida del menú para el modo foco, donde la barra se oculta y
        # no habría acceso a «Configurar modelo» ni «Recientes» hasta pulsar
        # F11. Comparte el mismo `menu_archivo`, así que ofrece lo mismo.
        self.boton_foco = ttk.Menubutton(self, text="☰  Menú", menu=self.menu_archivo)
        # El pie se ancla antes que el área expansible: con pack, lo colocado
        # después es lo que se recorta al faltar espacio.
        self._build_pie()
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=es.ESP["md"], pady=(es.ESP["sm"], es.ESP["md"]))
        self.panes = panes
        # El artículo va primero y con más peso: es el foco del trabajo.
        self._build_editor(panes)
        self._build_asistente(panes)
        # La primera frase del enunciado debe llegar al historial, no al
        # buscador de la barra: el campo de entrada aún no existe cuando se
        # construye la barra, así que el foco y el empaquetado se resuelven
        # ahora que los tres paneles vivos están creados.
        self._preparar_enunciado_inicial()
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
        self._preparar_enunciado_inicial()
        self.editor.focus_set()
        # Iniciar el consumidor de eventos de UI (thread-safe)
        self.process_ui_events()

    @staticmethod
    def _tiene_enunciado(historial: Any) -> bool:
        """¿El historial ya conserva una conversación que merece restaurarse?"""
        try:
            contenido = historial.get("1.0", "end-1c").strip()
        except (AttributeError, tk.TclError):
            return False
        return bool(contenido)

    def _mostrar_documento_activo(self) -> None:
        """Nombre del artículo en la barra y en el título de la ventana.

        El título también indica si hay cambios sin guardar, de modo que una
        consulta rápida a la barra de tareas responda «qué tengo abierto».
        Solo actúa si la app ya está construida: `modified` puede dispararse
        durante el arranque, antes de que exista la barra.
        """
        barra = _widget_propio(self, "barra")
        if barra is None:
            return
        ruta = self.session.document_path
        try:
            if ruta is not None:
                self.title(f"{ruta.name}{' •' if self.session.dirty else ''} — Tukul")
            else:
                self.title("Tukul")
        except (tk.TclError, AttributeError):
            return
        try:
            barra.actualizar_documento(None if ruta is None else ruta.name)
        except (AttributeError, TypeError):
            pass

    def _mostrar_coste(self) -> None:
        """Devuelve su sitio a la línea de uso, una sola vez por petición.

        Se llama antes de cada `pack`: repetirlo en el mismo flujo movía la
        etiqueta al fondo del contenedor y descolocaba la ayuda vecina.
        """
        coste = _widget_propio(self, "cost_label")
        if coste is None or _widget_propio(self, "_coste_reservado"):
            return
        try:
            coste.pack(side="bottom", fill="x", pady=(es.ESP["xs"], 0))
        except (tk.TclError, AttributeError, TypeError):
            return
        self._coste_reservado = True

    def _preparar_enunciado_inicial(self) -> None:
        """Deja el enunciado en el historial y aparta los controles redundantes.

        Se ejecuta antes de que la ventana se muestre para que la primera
        frase nunca compita por el foco con el buscador de la barra (Tk enfoca
        el primer widget enfocable del recorrido) y para que el reparto de
        espacio con `pack` sea correcto.

        La etiqueta de uso (`cost_label`) es idéntica al texto de ayuda justo
        encima: se retira hasta que el modelo informe de consumo real.
        """
        if not self._tiene_enunciado(self.history):
            self.append("Tukul",
                "¡Hola! Soy Tukul, tu asistente de escritura.\n\n"
                "• **Escribe o pega** un artículo en el panel izquierdo.\n"
                "• **Pregúntame** cualquier cosa sobre tu texto en el chat de la derecha.\n"
                "• **Selecciona texto** y pregúntame solo sobre esa parte.\n"
                "• **Revisar artículo** analiza ortografía, gramática y estructura.\n\n"
                "Empieza con un mensaje o abre un documento con Ctrl+O.",
                es_respuesta=False)
        self.cost_label.pack_forget()
        self._vestir_cancelar(self.estado_actual in ESTADOS_ACTIVOS)

    def _alinear_panes_iniciales(self) -> None:
        """Da al artículo la mayor superficie inicial del espacio de trabajo."""
        if not self.panes.winfo_exists() or not self.asistente_visible:
            return
        ancho = self.panes.winfo_width()
        if ancho > 0:
            try:
                self.panes.sashpos(0, round(ancho * 0.64))
            except tk.TclError:
                pass

    def _build_barra(self) -> None:
        """Barra mínima: utiliza el componente TopBar."""
        callbacks: dict[str, Callable[..., object]] = {
            "save": self.save_document,
            "manage_references": self.manage_references,
            "toggle_asistente": self.toggle_asistente,
            "cambiar_tema": self._cambiar_tema,
            "settings": self.settings
        }

        # Necesitamos preparar el menú antes de crear TopBar
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

        self.barra = TopBar(self, callbacks, menu_archivo, self, self.theme)
        self.barra.pack(fill="x")

        # Referencias para métodos que aún esperan estos atributos en app
        self.boton_menu = self.barra.boton_menu
        self.boton_guardar = self.barra.boton_guardar
        self.references_button = self.barra.references_button
        self.sync_label = self.barra.sync_label
        self.boton_panel = self.barra.boton_panel
        self.boton_tema = self.barra.boton_tema
        self.profile_chip = self.barra.profile_chip
        self.tooltip_tema = self.barra.tooltip_tema

    def _build_editor(self, panes) -> None:
        callbacks: dict[str, Callable[..., object]] = {
            "modified": self.modified,
            "update_context": self.update_context,
            "schedule_stats": self.schedule_stats,
            "text_menu": self.text_menu
        }
        self.panel_editor = EditorPanel(panes, callbacks)
        panes.add(self.panel_editor, weight=64)
        self.editor = self.panel_editor.editor

    def _build_asistente(self, panes) -> None:
        callbacks: dict[str, Callable[..., object]] = {
            "send_message": self.send_message,
            "cancel_request": self.cancel_request,
            "review": self.review,
            "create_input": lambda parent: self._text(parent, height=3, wrap="word",
                                                     padx=es.ESP["sm"], pady=es.ESP["xs"],
                                                     highlightbackground=es.SUPERFICIE_ALTA),
            "create_history": lambda parent: self._text(parent, wrap="word", state="disabled",
                                                        padx=es.ESP["md"], pady=es.ESP["sm"],
                                                        background=es.SUPERFICIE_ALTA)
        }
        self.panel_asistente = AssistantPanel(panes, callbacks)
        panes.add(self.panel_asistente, weight=36)

        self.input = self.panel_asistente.input
        self.history = self.panel_asistente.history
        self.send_button = self.panel_asistente.send_button
        self.cancel_button = self.panel_asistente.cancel_button
        self.review_button = self.panel_asistente.review_button
        self.estado_label = self.panel_asistente.estado_label
        self.estado_ayuda = self.panel_asistente.estado_ayuda
        self.cost_label = self.panel_asistente.cost_label

        # Los controles se anclan abajo ANTES que el historial. Con pack, lo que
        # se coloca después es lo que se recorta al faltar espacio: al reservar
        # primero el compositor, las acciones primarias nunca desaparecen aunque
        # el panel se estreche. El reparto vive ahora en AssistantPanel.
        # Placeholder en el campo de entrada: orienta sin estorbar
        self._placeholder_activo = True
        self._placeholder_texto = "Escribe tu mensaje aquí…"
        self.input.insert("1.0", self._placeholder_texto)
        self.input.config(foreground=es.TEXTO_TENUE)

        def _on_input_focus_in(_event: object = None) -> None:
            """Limpia el placeholder al recibir el foco."""
            if self._placeholder_activo:
                self.input.delete("1.0", "end")
                self.input.config(foreground=es.TEXTO)
                self._placeholder_activo = False

        def _on_input_focus_out(_event: object = None) -> None:
            """Restaura el placeholder si el campo quedó vacío."""
            content = self.input.get("1.0", "end-1c").strip()
            if not content:
                self.input.delete("1.0", "end")
                self.input.insert("1.0", self._placeholder_texto)
                self.input.config(foreground=es.TEXTO_TENUE)
                self._placeholder_activo = True

        self.input.bind("<FocusIn>", _on_input_focus_in)
        self.input.bind("<FocusOut>", _on_input_focus_out)
        self.input.bind("<Return>", self._on_input_return)
        self.input.bind("<Control-Return>", lambda e: self.input.insert("insert", "\n") or "break")
        self.input.bind("<Button-3>", self.text_menu)
        self.history.bind("<Button-3>", self.history_menu)
        self.history.bind("<Control-c>", lambda e: self.history.event_generate("<<Copy>>") or "break")
        # Copiar el mensaje completo bajo el cursor, sin seleccionar: los chats
        # suelen ofrecerlo, y en un panel de solo lectura seleccionar con el
        # ratón no siempre deja el cursor donde se hizo clic.
        self.history.bind("<Control-Shift-c>", self._on_copiar_mensaje_atajo)

        # Variables de estado que se vincularán dinámicamente
        self.estado_ayuda_var = tk.StringVar(value=EstadoUI.REPOSO.ayuda)
        self.estado_ayuda.config(textvariable=self.estado_ayuda_var)
        self.activity_var = tk.StringVar(value=EstadoUI.REPOSO.etiqueta())
        self.estado_label.config(textvariable=self.activity_var)
        self.cost_label_var = tk.StringVar(value="Se enviará el artículo activo; el contexto adicional se confirma antes de enviar.")
        self.cost_label.config(textvariable=self.cost_label_var)

        # Confirmación de contexto (gestionada por AssistantPanel)
        self.estado_actual = EstadoUI.REPOSO
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

    def _manejador_atajo(self, accion: Callable[[], object]) -> Callable[[object], str]:
        """Envuelve una acción como manejador de evento que detiene la propagación.

        Los atajos se registran con `bind_all`, así que también llegan mientras
        hay un diálogo modal abierto. Sin esta guarda, `Ctrl+S` guardaba el
        artículo y `Ctrl+O` abría el selector de archivos DEBAJO del diálogo:
        acciones destructivas actuando sobre la ventana equivocada. Cuando el
        evento nace en otra ventana (un Toplevel, un diálogo), se ignora para
        que el diálogo lo gestione: Escape ya cierra los suyos.
        """
        def manejador(evento: object) -> str:
            """Ejecuta la acción asociada al atajo solo desde la ventana principal."""
            widget = getattr(evento, "widget", None)
            if widget is not None:
                try:
                    if widget.winfo_toplevel() is not self.winfo_toplevel():
                        return ""
                except (AttributeError, tk.TclError):
                    pass
            accion()
            return "break"
        return manejador

    def toggle_foco(self) -> None:
        """Modo foco: deja solo el artículo, sin barra ni pie (F11 para salir).

        La barra completa se oculta porque su propósito es reducir distracción,
        pero se conserva el botón de menú (`boton_foco`): sin él no había forma
        de abrir «Configurar modelo» ni «Recientes» hasta salir del modo, y
        F11 es el único atajo de salida documentado.
        """
        if not self._foco_activo:
            self._foco_previo_asistente = self.asistente_visible
            self._foco_activo = True
            self.boton_foco.pack(side="left", padx=(es.ESP["sm"], 0), pady=(es.ESP["xs"], 0),
                                 before=self.panes)
            self.barra.pack_forget()
            self.pie.pack_forget()
            if self.asistente_visible:
                self.panes.forget(self.panel_asistente)
            self.status.set("Modo foco: solo el artículo (F11 para salir).")
            self.editor.focus_set()
        else:
            self._foco_activo = False
            self.boton_foco.pack_forget()
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
        """Mantiene el botón coherente con la visibilidad del panel.

        El texto es fijo («Panel IA»): el nombre del control no cambia, solo su
        estado. Quien dice qué hará (ocultar o mostrar) es el tooltip, porque
        al variar el ancho del botón la barra completa se desplazaba cada vez
        que se plegaba el panel.
        """
        if self.asistente_visible:
            self.boton_panel.config(text="◧  Panel IA  (F6)")
        else:
            self.boton_panel.config(text="◨  Panel IA  (F6)")
        tooltip = getattr(getattr(self, "barra", None), "tooltip_panel", None)
        if tooltip is not None:
            tooltip.set_texto("Ocultar el panel IA (F6)" if self.asistente_visible
                              else "Mostrar el panel IA (F6)")

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
        if who=="Tukul" and es_respuesta: self.scope.last_response=text
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
        self.activity_var.set(estado.etiqueta(detalle))
        self.estado_ayuda_var.set(estado.ayuda)
        try:
            self.estado_label.config(foreground=estado.color)
            # El nombre accesible viaja aparte del color y del símbolo.
            self.estado_label.config(text=self.activity_var.get())
        except tk.TclError:
            pass
        self._sincronizar_acciones(estado)

    def _vestir_cancelar(self, activo: bool) -> None:
        """Reusa el traje del botón «Cancelar» para el widget real de la app."""
        cancelar = _widget_propio(self, "cancel_button")
        if cancelar is not None and callable(getattr(cancelar, "configure", None)):
            _vestir_cancelar(cancelar, activo)

    def _sincronizar_acciones(self, estado: EstadoUI) -> None:
        """Habilita las acciones según haya o no una consulta viva.

        Con una consulta en vuelo, Enviar y Revisar esperan y «Cancelar» es la
        acción viva. Al cerrarla (éxito, error o cancelación) vuelven a
        habilitarse. Antes Enviar se habilitaba ante error/cancelación y se
        apagaba ante éxito, así que el primer éxito lo dejaba muerto.
        """
        activo = estado in ESTADOS_ACTIVOS
        # «Guardar» no entra aquí: su disponibilidad depende de que haya un
        # documento, no de si hay una consulta en vuelo. Guardar mientras el
        # modelo responde es legítimo y no pierde nada.
        # Cancelar se fija ANTES que las demás: el foco de ttk al habilitarlo
        # se lleva al primer widget enfocable posterior del recorrido, y la
        # sincronización no debe cambiar dónde está el foco más de una vez.
        #          «Cancelar» se queda visible en reposo, pero sin relieve
        #          («aquí no hay nada que cancelar») en vez de gris y con borde.
        cancelar = _widget_propio(self, "cancel_button")
        if cancelar is not None:
            _aplicar_estado_ttk(cancelar, activo)
            _vestir_cancelar(cancelar, activo)
        for nombre, disponible in (
            ("send_button", not activo),
            ("review_button", not activo),
        ):
            # Los dobles de prueba registran `state([...])`: se aplican los
            # estados ttk con el mismo argumento que usaba `_reset_request_ui`
            # para no invalidar ese contrato.
            widget = _widget_propio(self, nombre)
            if widget is None:
                continue
            _aplicar_estado_ttk(widget, disponible)

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
        self._popup_efimero(menu, event)
        return "break"

    @staticmethod
    def _popup_efimero(menu: tk.Menu, event) -> None:
        """Muestra un menú contextual y lo destruye al cerrarse.

        Antes cada clic derecho creaba un `tk.Menu` hijo de la raíz y nunca lo
        destruía: los menús se acumulaban durante la sesión. El `destroy()` va en
        `finally` porque `tk_popup` no retorna hasta que el menú se cierra (con o
        sin excepción, incluido el caso de que el usuario cierre la ventana).
        """
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass
            menu.destroy()

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
        self._popup_efimero(menu, event)
        return "break"

    def _rango_del_mensaje(self, indice: str) -> tuple[str, str] | None:
        """Devuelve el mensaje (voz, cuerpo o nota) que contiene ese índice.

        `tag_nextrange`/`tag_prevrange` devuelven el primer o último rango de la
        etiqueta, no el que contiene la posición: con varios mensajes del mismo
        tipo, copiar sobre uno devolvía siempre el más cercano al inicio. Se
        recorre la lista completa y se comprueba la contención.
        """
        for etiqueta in ("cuerpo_usuario", "cuerpo_bot", "nota"):
            rangos = self.history.tag_ranges(etiqueta)
            for inicio, final in zip(rangos[::2], rangos[1::2], strict=False):
                if (self.history.compare(indice, ">=", inicio)
                        and self.history.compare(indice, "<", final)):
                    return str(inicio), str(final)
        return None

    def _on_copiar_mensaje_atajo(self, _event=None) -> str:
        """Atajo Ctrl+Mayús+C: copia el mensaje completo bajo el cursor."""
        self._copiar_mensaje_en_cursor()
        return "break"

    def _copiar_mensaje_en_cursor(self) -> None:
        """Copia el mensaje completo que hay bajo el cursor de inserción."""
        class _Cursor:
            def __init__(self, x: int, y: int) -> None:
                self.x, self.y = x, y

        bbox = self.history.bbox("insert")
        x, y = (bbox[0] + 1, bbox[1] + 1) if bbox else (1, 1)
        self._copiar_mensaje(_Cursor(x, y))

    def _copiar_mensaje(self, event) -> None:
        """Copia el mensaje que contiene al cursor (voz, cuerpo o nota)."""
        rango = self._rango_del_mensaje(f"@{event.x},{event.y}")
        if rango is None:
            self.status.set("No hay mensaje aquí.")
            return
        texto = self.history.get(*rango).strip()
        if not texto:
            self.status.set("No hay mensaje aquí.")
            return
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.status.set("Mensaje copiado.")
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
        """Alinea el botón de revisión y el pie con el ámbito del editor.

        Firma pública sin argumentos: los widgets del editor la invocan como
        callback de evento y los tests la llaman desnuda.
        """
        selected=self.editor.get("sel.first","sel.last").strip() if self.editor.tag_ranges("sel") else ""
        # El pie es el reporte de lo ÚLTIMO que ocurrió, no un espejo del
        # contexto: sobrescribirlo al seleccionar borraba «Documento abierto:
        # …» o el aviso de error. Con una consulta viva o un error sin resolver
        # lo que informa el estado manda; el ámbito se ve en «Revisar artículo /
        # selección» y en las métricas del pie.
        if self.estado_actual in ESTADOS_ACTIVOS or self.estado_actual is EstadoUI.ERROR:
            self.schedule_stats()
            return
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
        error_msg = str(exc_value)
        # Mensaje humano: si es un error técnico conocido, lo traduce
        if "TclError" in type(exc_value).__name__ or "tk" in error_msg.lower():
            user_msg = "La interfaz tuvo un pequeño contratiempo. Puedes continuar trabajando."
        elif "memory" in error_msg.lower():
            user_msg = "Tukul se quedó sin memoria. Guarda tu trabajo y reinicia la aplicación."
        elif "permission" in error_msg.lower() or "denied" in error_msg.lower():
            user_msg = "No tengo permisos para acceder a un archivo. Revisa los permisos del sistema."
        else:
            user_msg = "Algo no salió como esperaba. Puedes continuar o reiniciar Tukul."
        self.status.set(f"⚠ {user_msg}")
        # Solo mostrar diálogo si el error no es trivial
        if not any(skip in error_msg.lower() for skip in ["geometry", "winfo", "tcl"]):
            messagebox.showerror(
                "Algo ocurrió",
                f"{user_msg}\n\nSi el problema persiste, revisa el registro en ~/.local/state/tukul/tukul.log",
                parent=self,
            )
    def show_error(self, title: str, detail: str, next_step: str | None = None) -> None:
        """Muestra un error y, si existe, el siguiente paso accionable."""
        self.status.set(f"{title}. Siguiente paso: {next_step}" if next_step else title)
        logger.error("Error visible en UI: %s — %s", title, detail)
        # La ruta del registro es el único dato que permite investigar después
        # de cerrar el diálogo: sin ella, «quedaron registrados» no dice dónde.
        registro = next(
            (handler.baseFilename for handler in logger.handlers
             if isinstance(handler, logging.FileHandler)), None,
        )
        pista = (f"\n\nDetalles en: {registro}" if registro
                 else "\n\nNo hay archivo de registro disponible en esta instalación.")
        siguiente = f"\n\nSiguiente paso: {next_step}" if next_step else ""
        messagebox.showerror(
            title,
            "No pudimos completar la acción. Vuelve a intentarlo." + siguiente + pista,
            parent=self,
        )
    def load_document(self, path: Path) -> bool:
        """Sustituye el artículo activo y su conversación, cada una por documento."""
        self.status.set(f"Cargando {path.name}…")
        self.update_idletasks()
        success, error, session = self.docs.open_document(path)
        if not success:
            self.show_error(
                "No se pudo abrir el documento",
                f"{path}\n\n{error}",
                "Usa Menú > Abrir artículo… o Ctrl+O para elegir otro archivo.",
            )
            return False
        documento = session.document_path
        if documento is None:
            self.show_error(
                "No se pudo abrir el documento",
                f"{path}\n\nSin ruta de destino.",
                "Usa Menú > Abrir artículo… o Ctrl+O para elegir otro archivo.",
            )
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
                self.append("Tú" if item.role == "user" else "Tukul", item.content)
        else:
            # Reabrir el mismo documento (p. ej. desde «Recientes»): el artículo
            # en disco se recarga, pero la conversación en curso no se toca. Por
            # eso NO se llama a `set_session`: sustituiría la sesión viva por una
            # nueva y un worker en curso seguiría escribiendo en la vieja; la
            # respuesta se pintaba en pantalla pero no se guardaba.
            self.session.article = session.article
            self.session.document_path = session.document_path
            self.session.project_path = session.project_path
        self._enter_document_scope(session.document_path)
        self._replace_editor_text(session.article)
        self.append("Tukul", f"Artículo activo: «{path.name}». La conversación y los artículos "
                    "de contexto se conservan para continuar el trabajo.",
                    es_respuesta=False)
        self._registrar_reciente(path)
        self.session.dirty=False; self._sincronizar_estado_sync("clean")
        self._mostrar_documento_activo()
        self.update_context(); self.schedule_stats(); self.status.set(f"Documento abierto: {path.name}")
        return True

    def _clear_history_widget(self) -> None:
        """Vacía el panel de conversación (el estado ya vive en la sesión)."""
        self.history.config(state="normal")
        self.history.delete("1.0", "end")
        self.history.config(state="disabled")
    def _enviar_desde_input(self) -> None:
        """Extrae el mensaje del input respetando el placeholder y lo envía."""
        if self._placeholder_activo:
            return
        message = self.input.get("1.0", "end-1c").strip()
        if not message or self.session.request_active:
            return
        # Validar ANTES de pintar el turno: sin perfil/key el mensaje quedaría
        # como un turno fantasma del usuario que nunca recibe respuesta.
        if not self.profile.enabled or not self._resolver_credenciales():
            if self.active_profile in self._llaves_en_curso:
                # La key del llavero aún se está leyendo: se lanza en segundo
                # plano y el usuario puede reintentar en un instante.
                self.append("Tukul", "Recuperando la API key del llavero. "
                                     "Vuelve a enviar en un momento.")
            else:
                self.append("Tukul", "Configura un perfil LLM y una key para responder.")
            return
        self.input.delete("1.0", "end")
        # Restaurar placeholder tras enviar
        self._placeholder_activo = True
        self.input.insert("1.0", self._placeholder_texto)
        self.input.config(foreground=es.TEXTO_TENUE)
        self.append("Tú", message)
        self.request(message)

    def _on_input_return(self, _event: object = None) -> str:
        """Enter envía el mensaje y detiene la propagación del evento."""
        self._enviar_desde_input()
        return "break"

    def _resolver_credenciales(self) -> str:
        """Key del perfil activo sin bloquear el hilo de Tk.

        Devuelve lo que haya en memoria (entorno, sesión o caché del llavero) y
        lanza la lectura del llavero en segundo plano si aún no se hizo. El
        envío real comprueba la credencial en su worker, así que un fallo de
        lectura nunca congela la interfaz.
        """
        if (os.environ.get(self.profile.api_key_env)
                or self.session_keys.get(self.active_profile, "")):
            return self.key
        if self.active_profile not in self._keys_llavero:
            self._prime_key()
            return ""
        return self._keys_llavero.get(self.active_profile, "")

    def _esperar_key(self, timeout: float = KEYRING_TIMEOUT_SECONDS) -> str:
        """Resuelve la key esperando la lectura del llavero.

        Solo se invoca desde un worker: `Event.wait` libera el GIL y el tope
        evita esperas ilimitadas si el llavero no responde.
        """
        if self.key:
            return self.key
        perfil = self.active_profile
        if perfil not in self._keys_llavero:
            self._prime_key()
            listo = self._llaves_en_curso.get(perfil)
            if listo is not None:
                listo.wait(timeout)
        return self.key

    def send_message(self):
        """Envía el mensaje del cuadro de entrada como consulta normal."""
        self._enviar_desde_input()
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
            self.append("Tukul", "Configura un perfil LLM y una key para responder."); return

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
        # La conversación la construye `prompting`, dueño del contrato de salida.
        conversacion = [ChatMessage("user", REVIEW_PROMPT)]
        try:
            prompt = build_review_prompt(texto)
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

        # El ciclo de la petición vive en `RequestLifecycle`; aquí solo queda
        # lo que es de la interfaz (validar tamaño y anunciar el estado).
        self._ciclo_peticion().start(
            request_id=request_id, profile=profile, article=texto, packet="",
            conversation=conversacion, cancel_event=cancel_event,
            request_type="review",
        )

    def request(self, message: str, request_type: str = "normal"):
        """Envía una consulta sobre el artículo, sin explorar archivos locales.

        El artículo abierto (o la selección) es el único contexto automático.
        Las referencias de archivos deben ser una acción explícita del usuario;
        buscar el workspace por cada mensaje hacía que una consulta normal se
        detuviera pidiendo permiso para compartir documentación no solicitada.
        """
        # Guarda de reentrada: dos envíos simultáneos reutilizaban la misma
        # ventana de estado y la respuesta del primero se pintaba sobre la
        # segunda petición. Se descarta mientras haya una viva o pendiente de
        # aprobación (confirm_and_send aún no marcó el worker como lanzado).
        # «Espera o cancélala» prometía un botón que queda retirado del layout
        # fuera de una petición: aquí solo se puede esperar.
        if self.session.request_active:
            self.status.set("Ya hay una consulta en curso; espera a que termine para enviar otra.")
            return
        if not self.profile.enabled or not self.key: self.append("Tukul","Configura un perfil LLM y una key para responder."); return
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
            ceiling = (MAX_THREAT_FEED_EXCERPT_CHARS
                       if article.source_id == THREAT_FEED_SOURCE_ID
                       else MAX_CONTEXT_EXCERPT_CHARS)
            excerpt = article.content[:min(ceiling, remaining)]
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
        self.cost_label_var.set(detail)
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
        # Snapshot en el hilo de UI: el worker no lee estado mutable de la sesión.
        self._ciclo_peticion().start(
            request_id=request_id, profile=profile, article=selected, packet=packet,
            conversation=conversation_with_message, cancel_event=cancel_event,
            request_type=request_type, files=files,
        )

    def _pedir_aprobacion(self, request_id: int, files: list[str],
                          key: ContextApprovalKey, al_aceptar) -> None:
        """Muestra la confirmación de contexto dentro del panel del asistente."""
        text = (
            "Se enviará el artículo activo de la izquierda y "
            f"{len(files)} artículo(s) de contexto al proveedor: "
            + ", ".join(files)
        )
        self.set_estado(EstadoUI.PREPARANDO, "esperando tu confirmación")

        def aceptar() -> None:
            """Acepta la autorización del contexto y lanza el envío."""
            self.panel_asistente.hide_approval()
            # Desalojar la aprobación más antigua, no las 128: vaciar el conjunto
            # entero obligaba a reconfirmar todo de golpe.
            self.approved_contexts.remember(key)
            al_aceptar()
            # Devolver el foco al editor para seguir trabajando
            self.editor.focus_set()

        def rechazar() -> None:
            """Rechaza la autorización y aborta la petición."""
            self.panel_asistente.hide_approval()
            self._abort_request(request_id)
            self.set_estado(EstadoUI.CANCELADO, "no se envió nada")
            # Devolver el foco al editor tras rechazar
            self.editor.focus_set()

        self.panel_asistente.show_approval(text, aceptar, rechazar)

    def _ciclo_peticion(self) -> RequestLifecycle:
        """Ciclo de petición con los canales de ESTA ventana.

        Se construye por llamada (es barato): así los canales son los vivos
        aunque un test los sustituya, y no hay estado duplicado que mantener.
        """
        return RequestLifecycle(
            chunks=self.chunks,
            publicar=self.control_queue.put_nowait,
            session=self.llm,
            arrancar=WorkerThreads.start,
            esperar_key=lambda: self.key or self._esperar_key(),
        )

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
        if usage[0] is not None:
            self.cost_label_var.set(f"Uso real: {usage[0]:,} entrada · {usage[1] or 0:,} salida")
            self._mostrar_coste()

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
                self.append("Tukul", result)
            return

        self.set_estado(EstadoUI.EXITO)
        self.session.conversation.append(ChatMessage("assistant",result))
        if streamed: self.scope.last_response=result
        else: self.append("Tukul",result)

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
            # Red de seguridad de la aplicación: aunque el SYSTEM_PROMPT pida
            # resistir las inyecciones, si el modelo obedeció y devolvió el texto
            # del atacante (o sus propias instrucciones) hay que decirlo como
            # fallo, no presentar esa prosa como si fuera una revisión.
            motivo = self.respuesta_fuera_de_rol(result)
            if motivo is not None:
                self.set_estado(EstadoUI.ERROR, "la respuesta salió del rol de revisor")
                self._append_notice(
                    f"La revisión se descartó: {motivo}. El artículo parece contener "
                    "instrucciones dirigidas al sistema. Elimínalas del texto y vuelve a intentarlo."
                )
                return
            # Cada causa se dice por separado. Antes las cuatro se presentaban
            # como fallo del modelo, incluida la que no lo es: un artículo sin
            # hallazgos es un resultado correcto.
            causa, _ = diagnose_findings(result)
            if causa == "sin_hallazgos":
                self.set_estado(EstadoUI.EXITO, "sin hallazgos")
                self._append_notice("Revisión terminada: no se encontraron hallazgos que corregir.")
                return
            self.set_estado(EstadoUI.ERROR, "la respuesta no era una revisión válida")
            aviso = {
                "sin_json": "El modelo respondió en prosa en vez de la revisión estructurada.",
                "esquema_ajeno": "El modelo devolvió otro formato de revisión, no el esperado.",
                "truncado": "La revisión llegó incompleta y no se pudo leer.",
            }.get(causa, "El modelo no devolvió una revisión utilizable.")
            self._append_notice(f"{aviso} Prueba con un fragmento más corto o con otro modelo.")
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
        """Devuelve los botones al estado de reposo al cerrar una petición.

        Libera Enviar y Revisar y devuelve «Cancelar» a su traje inactivo
        (sigue visible). Antes solo liberaba Enviar, así que Revisar seguía
        esperando tras un cierre por error o cancelación. «Guardar» queda
        fuera: depende del documento, no de la consulta.
        """
        for nombre in ("send_button", "review_button"):
            widget = _widget_propio(self, nombre)
            if widget is not None:
                _aplicar_estado_ttk(widget, True)
        self._vestir_cancelar(False)

    def stream_chunk(self, request_id, value):
        """Pinta un fragmento incremental de la respuesta en curso."""
        # Verificar que este request_id sigue siendo válido (no cancelado/descartado)
        if self.closing or request_id not in self.request_types:
            return
        if self.streaming_request != request_id:
            self.streaming_request = request_id
            self.streaming_text = ""
            self.history.config(state="normal")
            self.history.insert("end", "Tukul\n", "rotulo_bot")
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
        # Feedback visible y accionable
        self._append_notice("Has cancelado la consulta. Puedes enviar un nuevo mensaje o seguir editando.")
        self.status.set("✕ Consulta cancelada.")
        # Restaurar el placeholder en el input si estaba vacío
        if self._placeholder_activo:
            self.input.delete("1.0", "end")
            self.input.insert("1.0", self._placeholder_texto)
            self.input.config(foreground=es.TEXTO_TENUE)
        self.editor.focus_set()

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

        elif event_type == "keyring_unavailable":
            # Aviso no modal: el envío fallará con «falta la key», pero la causa
            # real (llavero sin respuesta) debe quedar visible en el pie.
            _, perfil = event
            self.status.set(
                f"⚠ El llavero no responde (perfil «{perfil}»). "
                "Revisa el servicio de credenciales o usa la variable de entorno."
            )

    def _flush_pending_chunks(self, request_id: int) -> None:
        """Vuelca lo acumulado de una petición antes de cerrarla.

        Garantiza que ningún fragmento recibido se pierda por llegar el
        `complete` en el mismo ciclo que los últimos chunks.
        """
        texto = self.chunks.take(request_id)
        if texto and self.request_types.get(request_id) == "normal":
            self.stream_chunk(request_id, texto)

    parse_findings = staticmethod(parse_findings)
    diagnose_findings = staticmethod(diagnose_findings)
    respuesta_fuera_de_rol = staticmethod(respuesta_fuera_de_rol)
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

    # ─── Contexto de artículos y fuente CVE (pipeline en `tukul_ui.contexto_dialogo`) ──
    # La ventana sigue siendo la dueña de `context_articles`; aquí solo se
    # conserva una fachada que mantiene la API histórica y delega en el controlador.

    @property
    def _contexto(self) -> ContextController:
        """Controlador de contexto, creado perezosamente y reutilizado."""
        ctrl = getattr(self, "_contexto_ctrl", None)
        if ctrl is None:
            ctrl = ContextController(
                self,
                threat_feed_hours=THREAT_FEED_HOURS,
                threat_feed_source_id=THREAT_FEED_SOURCE_ID,
                max_indexed_file_bytes=MAX_INDEXED_FILE_BYTES,
            )
            self._contexto_ctrl = ctrl
        return ctrl

    def _update_references_button(self) -> None:
        """Delega en `ContextController.update_references_button`."""
        self._contexto.update_references_button()

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
        """Delega en `ContextController.add_current_article_to_context`."""
        return self._contexto.add_current_article_to_context()

    def _authorize_context_articles(self) -> None:
        """Autoriza el conjunto actual para el destinatario activo, una sola vez."""
        packet, files = self._reference_packet()
        self.approved_contexts.remember_for(self.profile, packet, files)

    def _fetch_threat_feed(self, dialog: tk.Toplevel, on_done: Callable[[], None]) -> None:
        """Delega en `ContextController.fetch_threat_feed`."""
        self._contexto.fetch_threat_feed(dialog, on_done)

    def _on_threat_feed_error(self, dialog: tk.Toplevel, detail: str) -> None:
        """Delega en `ContextController.on_threat_feed_error`."""
        self._contexto.on_threat_feed_error(dialog, detail)

    def _on_threat_feed_ready(self, packet: str, files: list[str],
                              on_done: Callable[[], None]) -> None:
        """Delega en `ContextController.on_threat_feed_ready`."""
        self._contexto.on_threat_feed_ready(packet, files, on_done)


    # ─── Sugerencia de impacto ─────────────────────────────────────────────────

    # ─── Ideas de artículo (pipeline extraído a `tukul_ui.ideas`) ───────────
    # El controlador recibe esta app por inyección; aquí solo se conserva una
    # fachada que mantiene la API histórica para no romper a los consumidores.

    @property
    def _ideas(self) -> IdeasController:
        """Controlador de ideas, creado perezosamente y reutilizado."""
        ctrl = getattr(self, "_ideas_ctrl", None)
        if ctrl is None:
            ctrl = IdeasController(self, FEED_CACHE_DIR, THREAT_FEED_HOURS)
            self._ideas_ctrl = ctrl
        return ctrl

    def _fetch_impact_suggestion(self, dialog: tk.Toplevel,
                                 on_done: Callable[[], None]) -> None:
        """Delega en `IdeasController.fetch_suggestion`."""
        self._ideas.fetch_suggestion(dialog, on_done)

    def _ejecutar_pipeline_ideas(self, dialog, profile, api_key, cache_path,
                                 on_done: Callable[[], None]) -> bool:
        """Delega en el pipeline del controlador (se ejecuta en el worker)."""
        return self._ideas._ejecutar_pipeline(dialog, profile, api_key, cache_path, on_done)

    @staticmethod
    def _llm_de_ideas(profile, api_key) -> Callable[[str], str] | None:
        """Delega en `IdeasController._llm_de_ideas`."""
        return IdeasController._llm_de_ideas(profile, api_key)

    def _registrar_error_ideas(self, dialog, detalle: str) -> None:
        """Delega en el controlador (publica el error en el hilo de Tk)."""
        self._ideas._registrar_error(dialog, detalle)

    def _publicar_error_ideas(self, dialog, mensaje: str) -> None:
        """Delega en el controlador."""
        self._ideas._publicar_error(dialog, mensaje)

    def _show_idea_selection_dialog(self, parent_dialog: tk.Toplevel,
                                    ideas: list[ArticleIdea],
                                    all_entries: list[FeedEntry],
                                    correlations: list[CorrelationGroup],
                                    on_done: Callable[[], None]) -> None:
        """Delega en `IdeasController.show_selection_dialog`."""
        self._ideas.show_selection_dialog(
            parent_dialog, ideas, all_entries, correlations, on_done)

    def _reaplicar_tema_ideas(self, dialog: tk.Toplevel, idea_listbox: tk.Listbox,
                              preview: ttk.Label) -> None:
        """Delega en `IdeasController._reaplicar_tema`."""
        self._ideas._reaplicar_tema(dialog, idea_listbox, preview)

    def _on_impact_suggestion_error(self, dialog: tk.Toplevel, detail: str) -> None:
        """Delega en `IdeasController._on_error`."""
        self._ideas._on_error(dialog, detail)


    def _ask_to_authorize_articles(self, labels: list[str], parent) -> bool:
        """Delega en `ContextController.ask_to_authorize_articles`."""
        return self._contexto.ask_to_authorize_articles(labels, parent)

    def _add_references(self, paths: tuple[str, ...] | list[str]) -> int:
        """Delega en `ContextController.add_references`."""
        return self._contexto.add_references(paths)

    def manage_references(self) -> None:
        """Delega en `ContextController.manage_references`."""
        self._contexto.manage_references()

    def _reaplicar_tema_contexto(self, dialog: tk.Toplevel, entries: tk.Listbox) -> None:
        """Delega en `ContextController.reaplicar_tema_contexto`."""
        self._contexto.reaplicar_tema_contexto(dialog, entries)


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
        options: dict = {"defaultextension": ".tukul.json", "filetypes": [("Proyecto","*.tukul.json")]}
        # El proyecto guarda rutas relativas: proponer la carpeta del artículo evita
        # la ruta imposible (el artículo debe quedar bajo la carpeta del proyecto).
        options["initialdir"] = str(self.session.document_path.parent)
        options["initialfile"] = f"{self.session.document_path.stem}.tukul.json"
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
        path=filedialog.askopenfilename(filetypes=[("Proyecto Tukul","*.tukul.json")])
        if not path:return
        # Carga a través del DocumentManager: el flujo estaba duplicado aquí y allí,
        # con manejo de errores divergente y la copia del manager sin usar ni probar.
        success, error, session = self.docs.open_project(Path(path))
        if not success:
            messagebox.showerror("Proyecto no válido", error); return
        self.docs.set_session(session)
        self._replace_editor_text(self.session.article)
        self._clear_history_widget()
        for item in self.session.conversation:self.append("Tú" if item.role=="user" else "Tukul",item.content)
        self._enter_document_scope(self.session.document_path)
        self.session.dirty=False; self._sincronizar_estado_sync("clean")
        self._mostrar_documento_activo()
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
        # Se marca el evento DE ESTA petición. Antes se llamaba a
        # `llm.cancel(...)`, que marcaba `llm.cancel_event`: el evento de la
        # última petición lanzada, que no tiene por qué ser la que se cancela.
        # El worker ya recibió su evento por parámetro, así que este es el único
        # canal que importa; cerrar el socket se hace igualmente abajo.
        if self.cancel_event:
            self.cancel_event.set()
        # Cancelar en LLMClient (generation_counter es el request_id actual).
        self.llm.client.cancel(self.generation_counter)
        # Limpiar TODOS los buffers pendientes: una respuesta tardía no debe
        # pintarse ni reactivar una petición ya cerrada.
        self.request_types.clear()
        self.chunks.clear()
        self.streaming_request = None
        self.streaming_text = ""
        self.session.request_active = False
        self._reset_request_ui()
        # Si se canceló mientras se esperaba la confirmación de contexto, la
        # barra de aprobación queda huérfana y hay que retirarla. Vive en
        # AssistantPanel desde el refactor de componentes.
        self.panel_asistente.hide_approval()

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
        # Se guarda con el mismo saneador que la restauración: Tk escribe las
        # negaciones como «+-61», que es correcto para Tk pero deja en disco
        # coordenadas que no caben en este escritorio. Normalizar aquí evita
        # reproducir el problema de apertura en la próxima sesión.
        # Si la ventana no se ha mapeado, `geometry()` devuelve su tamaño
        # pedido (p. ej. «1x1+0+0») y guardarlo encogería la próxima apertura:
        # en ese caso no se toca lo que ya había en `estado.json`.
        if self._ventana_mapeada():
            saneada = self._geometria_saneada(self.geometry(), self.winfo_screenwidth(),
                                              self.winfo_screenheight())
            if saneada is not None:
                estado["geometry"] = saneada
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
        self._esperar_hilos_de_keyring()
        super().destroy()

    def _esperar_hilos_de_keyring(self, timeout: float = KEYRING_TIMEOUT_SECONDS) -> None:
        """Espera (con tope) a que terminen las lecturas del llavero en curso.

        Si la ventana se destruye con una lectura viva, el hilo sigue asignando
        memoria y el recolector puede ejecutar `Variable.__del__` desde él, que
        toca Tcl fuera del hilo principal (`main thread is not in main loop`).
        El tope evita que un llavero colgado impida cerrar la aplicación.
        """
        pendientes = list(self._llaves_en_curso.values())
        if not pendientes:
            return
        limite = time.monotonic() + timeout
        for listo in pendientes:
            restante = limite - time.monotonic()
            if restante <= 0:
                break
            listo.wait(restante)

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
        vivos = WorkerThreads.esperar(timeout)
        if vivos:
            logger.warning("%d hilo(s) de petición seguían activos al cerrar", len(vivos))
