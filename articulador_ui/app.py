from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from articulador_core.llm import LlmError
from articulador_core.models import ArticleSession, ChatMessage, LlmProfile
from articulador_core import storage
from articulador_core.logging_config import setup_logging
from articulador_core.prompting import build_editor_prompt
from articulador_core.review import parse_findings
from articulador_ui.dialogs import show_context_dialog, show_review_dialog, show_settings_dialog
from articulador_ui.document_manager import DocumentManager
from articulador_ui.context_orchestrator import ContextOrchestrator
from articulador_ui.llm_session_manager import LLMSessionManager

COLORS = {"bg":"#151a20", "panel":"#1d252e", "raised":"#25313b", "field":"#10161c", "text":"#edf2f6", "muted":"#a9b7c4", "muted_light":"#bcc4d0", "accent":"#69c7b2", "accent_text":"#09231e", "border":"#3a4856", "selection":"#365f69", "assistant":"#c9b3ff"}
FONT = "DejaVu Sans"
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
        # Tamaño por defecto (se ajusta después en after_window_init)
        self.geometry("1180x760")
        self.minsize(720, 540)

        # LLM profiles
        self.config_path = config_path
        self.profiles, self.active_profile = storage.load_profiles(config_path)
        self.session_keys: dict[str, str] = {}
        self._session_keys_max = 32

        # Managers (refactorización de responsabilidades)
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.docs = DocumentManager()
        self.context = ContextOrchestrator(self.workspace_root)
        self.llm = LLMSessionManager()

        # Session & UI state (referencia dinámica a través de property)
        self.approved_contexts: set[tuple[str, ...]] = set()
        self.review_mode = False
        self.last_review_before = ""
        self.last_response = ""
        self.stats_after = None
        self.report_callback_exception = self.handle_callback_error
        self.cancel_event: threading.Event | None = None
        self.streaming_request: int | None = None
        self.streaming_text = ""
        self.closing = False

        # Contador de generación global (nunca reinicia) para prevenir contaminación de respuestas
        self.generation_counter = 0
        # Tipos de solicitud asociados a cada request_id
        self.request_types: dict[int, str] = {}  # request_id -> "normal"|"review"
        # Queue para thread-safety de Tkinter (worker → UI)
        # maxsize=1000 previene crecimiento descontrolado de memoria por eventos
        self.ui_event_queue: queue.Queue = queue.Queue(maxsize=1000)
        # Buffer para coalescer chunks (evitar procesar cada chunk por separado)
        self.pending_chunks: dict[int, list[str]] = {}  # request_id -> chunks acumulados

        # Inicializar widgets de UI explícitamente para evitar atributos implícitos
        self.panes: ttk.PanedWindow | None = None
        self.properties: ttk.Frame | None = None
        self.sync_label: ttk.Label | None = None
        self.profile_chip: ttk.Button | None = None
        self.context_label: ttk.Button | None = None
        self.history: ScrolledText | None = None
        self.input: ScrolledText | None = None
        self.send_button: ttk.Button | None = None
        self.cancel_button: ttk.Button | None = None
        self.activity: tk.StringVar | None = None
        self.cost_label: tk.StringVar | None = None
        self.editor: ScrolledText | None = None
        self.editor_stats: ttk.Label | None = None
        self.status: tk.StringVar | None = None
        self.last_context_files: list[str] = []

        self._theme()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        # Ajustar tamaño después de que la ventana esté lista
        self.after(100, self._adjust_window_size)

    @property
    def session(self) -> ArticleSession:
        """Referencia dinámica a sesión actual (siempre sincronizada con DocumentManager)."""
        return self.docs.session

    @property
    def profile(self) -> LlmProfile: return self.profiles[self.active_profile]
    @property
    def key(self) -> str: return os.environ.get(self.profile.api_key_env) or self.session_keys.get(self.active_profile, "") or storage.load_key(self.active_profile)

    def _add_session_key(self, profile: str, key: str) -> None:
        """Agrega key a sesión con límite de tamaño para evitar memory leak."""
        if len(self.session_keys) >= self._session_keys_max:
            # Remover la primera (más antigua) cuando se llena
            self.session_keys.pop(next(iter(self.session_keys)), None)
        self.session_keys[profile] = key

    def _adjust_window_size(self) -> None:
        """Ajusta tamaño de ventana tras inicialización (cuando winfo es confiable)."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        # Solo ajustar si pantalla es válida
        if screen_width > 100 and screen_height > 100:
            ideal_width = min(int(screen_width * 0.8), 1400)
            ideal_height = min(int(screen_height * 0.8), 900)
            min_width = max(800, int(screen_width * 0.4))
            min_height = max(600, int(screen_height * 0.4))
            self.geometry(f"{ideal_width}x{ideal_height}")
            self.minsize(min_width, min_height)

    def _theme(self) -> None:
        self.configure(bg=COLORS["bg"]); style = ttk.Style(self)
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=(FONT,10))
        style.configure("TFrame", background=COLORS["bg"]); style.configure("Panel.TFrame", background=COLORS["raised"])
        style.configure("TLabelframe", background=COLORS["panel"], bordercolor=COLORS["border"])
        style.configure("TLabelframe.Label", background=COLORS["panel"], foreground=COLORS["accent"], font=(FONT,10,"bold"))
        style.configure("TButton", background=COLORS["raised"], foreground=COLORS["text"], bordercolor=COLORS["border"], padding=(8,5))
        # Estilos de botones diferenciados
        style.configure("Accent.TButton", background=COLORS["accent"], foreground=COLORS["accent_text"], padding=(12,7), font=(FONT,10,"bold"))
        style.map("Accent.TButton", background=[("active", "#8cdbc8")])
        style.configure("Secondary.TButton", background=COLORS["raised"], foreground=COLORS["accent"], bordercolor=COLORS["border"], padding=(8,5))
        style.map("Secondary.TButton", background=[("active", COLORS["panel"])])
        style.configure("Config.TButton", background=COLORS["panel"], foreground=COLORS["accent"], relief="flat", padding=(6,4))
        style.map("Config.TButton", background=[("active", COLORS["raised"])])

    def _text(self, parent, **kwargs):
        options = {"background": COLORS["field"], "foreground": COLORS["text"], "insertbackground": COLORS["accent"], "selectbackground": COLORS["selection"], "relief": "flat", "borderwidth": 0, "font": (FONT, 10)}
        options.update(kwargs)
        return ScrolledText(parent, **options)

    def _build(self) -> None:
        bar=ttk.Frame(self,padding=8); bar.pack(fill="x")
        file_menu=tk.Menu(self,tearoff=False,background=COLORS["raised"],foreground=COLORS["text"])
        for text, command in (("Abrir…",self.open_document),("Guardar",self.save_document),("Guardar como…",lambda:self.save_document()),("Guardar proyecto…",self.save_project),("Abrir proyecto…",self.open_project)):
            file_menu.add_command(label=text,command=command)
        file_button=ttk.Menubutton(bar,text="Archivo",menu=file_menu); file_button.pack(side="left",padx=(0,6))
        ttk.Button(bar,text="Guardar",style="Accent.TButton",command=self.save_document).pack(side="left")
        self.sync_label = ttk.Label(bar, text="● Cambios locales", foreground=COLORS["muted"])
        self.sync_label.pack(side="right")
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=(0,6))
        self.panes = panes
        chat=ttk.Labelframe(panes,text="Asistencia de Articulador",padding=8); panes.add(chat,weight=35)
        header=ttk.Frame(chat,style="Panel.TFrame",padding=8); header.pack(fill="x",pady=(0,7))
        ttk.Label(header,text="¿Qué quieres trabajar?",background=COLORS["raised"],font=(FONT,11,"bold")).pack(side="left")
        ttk.Button(header,text="Propiedades",style="Secondary.TButton",command=self.toggle_properties).pack(side="right")
        self.properties = ttk.Frame(chat, style="Panel.TFrame", padding=(8,0))
        self.properties.pack(fill="x", pady=(0,7))
        self.profile_chip = ttk.Button(self.properties, text=f"Modelo: {self.profile.model or 'sin configurar'}", style="Config.TButton", command=self.settings)
        self.profile_chip.pack(side="left", padx=(0,8), pady=6)
        self.context_label = ttk.Button(self.properties, text="Contexto: artículo completo", style="Config.TButton", command=self.context_dialog)
        self.context_label.pack(side="left", pady=6)
        self.properties.pack_forget()
        self.history = self._text(chat, wrap="word", state="disabled", padx=10, pady=9)
        self.history.configure(background=COLORS["raised"])
        self.history.pack(fill="both", expand=True)
        self.history.bind("<Button-3>",self.history_menu)
        self.history.bind("<Control-c>",lambda e:self.history.event_generate("<<Copy>>") or "break")
        self.history.tag_configure("you",foreground=COLORS["accent"],font=(FONT,10,"bold")); self.history.tag_configure("bot",foreground=COLORS["assistant"],font=(FONT,10,"bold","italic"))
        composer=ttk.Labelframe(chat,text="Mensaje",padding=8); composer.pack(fill="x",pady=(8,0))
        self.input=self._text(composer,height=4,wrap="word",padx=8,pady=7); self.input.pack(fill="x"); self.input.bind("<Return>",lambda e:self.send() or "break"); self.input.bind("<Control-Return>",lambda e:self.input.insert("insert","\n") or "break")
        row=ttk.Frame(composer); row.pack(fill="x",pady=(5,0)); self.send_button=ttk.Button(row,text="Enviar",style="Accent.TButton",command=self.send); self.send_button.pack(side="right"); self.cancel_button=ttk.Button(row,text="Cancelar",style="Secondary.TButton",command=self.cancel_request,state="disabled"); self.cancel_button.pack(side="right",padx=(0,6)); ttk.Button(row,text="Revisar artículo",style="Secondary.TButton",command=self.review).pack(side="left"); ttk.Button(row,text="Limpiar",style="Secondary.TButton",command=self.clear_history).pack(side="left",padx=(0,6))
        self.activity=tk.StringVar(value="Listo para conversar."); ttk.Label(composer,textvariable=self.activity,foreground=COLORS["muted_light"]).pack(anchor="w",padx=8,pady=(5,0))
        self.cost_label=tk.StringVar(value="Contexto y coste se mostrarán antes de enviar."); ttk.Label(composer,textvariable=self.cost_label,foreground=COLORS["muted_light"],font=(FONT,9)).pack(anchor="w",padx=8)
        editor=ttk.Labelframe(panes,text="Tu artículo · edición",padding=4); panes.add(editor,weight=65)
        self.editor=self._text(editor,undo=True,wrap="word",font=(FONT,12)); self.editor.pack(fill="both",expand=True); self.editor.bind("<<Modified>>",self.modified); self.editor.bind("<ButtonRelease-1>",lambda e:self.update_context())
        self.editor.bind("<Control-s>",lambda e:self.save_document() or "break")
        self.editor.bind("<KeyRelease>",lambda e:self.schedule_stats())
        self.editor_stats=ttk.Label(editor,text="0 palabras · 0 min de lectura",foreground=COLORS["muted_light"]); self.editor_stats.pack(anchor="e",padx=4,pady=(4,0))
        self.status=tk.StringVar(value="Listo."); ttk.Label(self,textvariable=self.status,padding=7,foreground=COLORS["muted"]).pack(fill="x")
        self.append("Articulador","Cuéntame qué quieres explorar o mejorar. Puedo usar el artículo completo o una selección."); self.input.focus_set()
        # Iniciar el consumidor de eventos de UI (thread-safe)
        self.process_ui_events()

    def append(self, who:str, text:str) -> None:
        self.history.config(state="normal"); self.history.insert("end",who+"\n","you" if who=="Tú" else "bot"); self.history.insert("end",text.strip()+"\n\n"); self.history.see("end"); self.history.config(state="disabled")
        if who=="Articulador": self.last_response=text
    def clear_history(self) -> None:
        """Limpia historial de conversación."""
        if messagebox.askyesno("Limpiar historial", "¿Limpiar el historial de conversación?"):
            self.history.config(state="normal"); self.history.delete("1.0","end"); self.history.config(state="disabled")
            self.session.conversation.clear(); self.status.set("Historial limpiado.")
    def toggle_properties(self):
        if self.properties.winfo_ismapped(): self.properties.pack_forget()
        else: self.properties.pack(fill="x",pady=(0,7),before=self.history)
    def copy_response(self):
        if not self.last_response:return
        self.clipboard_clear(); self.clipboard_append(self.last_response); self.status.set("Última respuesta copiada.")
    def history_menu(self,event):
        menu=tk.Menu(self,tearoff=False,background=COLORS["raised"],foreground=COLORS["text"],activebackground=COLORS["accent"],activeforeground=COLORS["accent_text"])
        menu.add_command(label="Copiar",command=lambda:self.history.event_generate("<<Copy>>"))
        menu.add_command(label="Seleccionar todo",command=lambda:self.history.tag_add("sel","1.0","end-1c"))
        menu.tk_popup(event.x_root,event.y_root); menu.grab_release()
        return "break"
    def modified(self,_=None):
        if self.editor.edit_modified(): self.session.dirty=True; self.editor.edit_modified(False); self.sync_label.config(text="● Cambios sin guardar",foreground=COLORS["accent"]); self.update_context(); self.schedule_stats()
    def schedule_stats(self):
        if self.stats_after: self.after_cancel(self.stats_after)
        self.stats_after=self.after(300,self.update_stats)
    def update_context(self):
        selected=self.editor.get("sel.first","sel.last").strip() if self.editor.tag_ranges("sel") else ""
        self.context_label.config(text=f"Contexto: selección · {len(selected.split())} palabras" if selected else "Contexto: artículo completo")
    def update_stats(self):
        self.stats_after=None; words=len(self.editor.get("1.0","end-1c").split()); self.editor_stats.config(text=f"{words:,} palabras · {max(1,round(words/220))} min de lectura" if words else "0 palabras · 0 min de lectura")
    def handle_callback_error(self, exc_type, exc_value, _traceback):
        logger.exception("Excepción no controlada de Tkinter", exc_info=(exc_type, exc_value, _traceback))
        self.status.set("Ocurrió un error interno. Puedes continuar o reiniciar Articulador.")
        messagebox.showerror("Error interno",str(exc_value),parent=self)
    def show_error(self, title: str, detail: str) -> None:
        self.status.set(title)
        messagebox.showerror(title, detail, parent=self)
    def load_document_content(self, path: Path, content: str) -> None:
        self.session.document_path=path.resolve(); self.session.article=content
        self.editor.delete("1.0","end"); self.editor.insert("1.0",content)
        self.session.dirty=False; self.sync_label.config(text="● Documento abierto",foreground=COLORS["muted"])
        self.update_context(); self.schedule_stats(); self.status.set(f"Documento abierto: {path.name}")
    def send(self):
        message=self.input.get("1.0","end-1c").strip()
        if not message or self.session.request_active:return
        self.input.delete("1.0","end"); self.append("Tú",message); self.request(message)
    def review(self):
        if not self.editor.get("1.0","end-1c").strip(): messagebox.showinfo("Falta artículo","Escribe o abre un artículo."); return
        if self.session.request_active: messagebox.showinfo("Request activa","Espera a que termine la consulta anterior."); return
        self.append("Tú", REVIEW_PROMPT)
        # Pasar review=True; request() manejará review_mode
        self.request(REVIEW_PROMPT, request_type="review")

    def request(self, message: str, request_type: str = "normal"):
        if not self.profile.enabled or not self.key: self.append("Articulador","Configura un perfil LLM y una key para responder."); return
        article = self.editor.get("1.0","end-1c")
        selected = self.editor.get("sel.first","sel.last") if self.editor.tag_ranges("sel") else article
        self.session.request_active=True; self.cancel_event=threading.Event(); self.send_button.state(["disabled"]); self.cancel_button.state(["!disabled"]); self.activity.set("Mensaje recibido. Articulador está analizando…")
        # Usar generation_counter global (nunca reinicia) para prevenir contaminación
        self.generation_counter += 1; request_id = self.generation_counter
        # Guardar el tipo de solicitud para este request_id
        self.request_types[request_id] = request_type
        cancel_event=self.cancel_event
        def work():
            try:
                success, packet, files = self.context.prepare_context(message, self.profile.max_context_chars//3)
                if not success:
                    # Publicar en queue en lugar de self.after()
                    self.ui_event_queue.put(("context_failed", request_id, "No se pudo indexar contexto"))
                    return
            except Exception as error:
                # Publicar en queue en lugar de self.after()
                self.ui_event_queue.put(("context_failed", request_id, str(error)))
                return
            if cancel_event.is_set(): return
            # Publicar en queue en lugar de self.after()
            self.ui_event_queue.put(("confirm_and_send", request_id, message, selected, packet, files, cancel_event))
        threading.Thread(target=work,daemon=True).start()
    def context_failed(self, request_id: int, error_msg: str) -> None:
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types: return
        logger.error("No se pudo preparar el contexto: %s", error_msg)
        self.session.request_active=False; self.send_button.state(["!disabled"]); self.cancel_button.state(["disabled"])
        # Limpiar review_mode si esta solicitud falló antes de enviar
        self.review_mode = False
        self.request_types.pop(request_id, None)
        self.activity.set("No se pudo preparar el contexto."); self.show_error("Error de contexto", error_msg)

    def confirm_and_send(self, request_id, message, selected, packet, files, cancel_event):
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types or cancel_event.is_set(): return
        self.last_context_files=files

        # Obtener el tipo de solicitud (normal/review) para este request_id
        request_type = self.request_types.get(request_id, "normal")

        # Construir conversation INCLUYENDO el mensaje actual (necesario para validación y envío)
        # Tomar últimos 12 mensajes previos + el actual
        conversation_with_message = list(self.session.conversation[-12:]) + [ChatMessage("user", message)]

        from articulador_core.prompting import build_editor_prompt
        from articulador_core.llm import SYSTEM_PROMPT, estimate_prompt_tokens

        # Validar límite GLOBAL contra el payload EXACTO (fail-closed)
        try:
            # Construir el prompt COMPLETO: SYSTEM_PROMPT + JSON con todo (articulo, contexto, conversation con mensaje)
            prompt_json = build_editor_prompt(selected, packet, conversation_with_message)
            actual_tokens = estimate_prompt_tokens(SYSTEM_PROMPT, prompt_json)

            # Validar límite ENTRADA + SALIDA: entrada + max_output_tokens <= max_total_model_tokens
            # actual_tokens YA está en tokens (calculado por estimate_prompt_tokens)
            max_allowed_tokens = self.profile.max_total_model_tokens - self.profile.max_output_tokens
            if actual_tokens > max_allowed_tokens:
                self.session.request_active=False
                self.send_button.state(["!disabled"])
                self.cancel_button.state(["disabled"])
                self.review_mode = False  # Limpiar review_mode si falla
                self.request_types.pop(request_id, None)
                self.show_error(
                    "Solicitud demasiado grande",
                    f"Entrada: ~{actual_tokens:,} tokens\n"
                    f"Salida reservada: ~{self.profile.max_output_tokens:,} tokens\n"
                    f"Límite total modelo: ~{self.profile.max_total_model_tokens:,} tokens\n\n"
                    f"Reduce el artículo, la conversación previa o el contexto local."
                )
                return
        except Exception as e:
            # Validación fail-closed: si hay error, rechazar la solicitud
            logger.error("Error crítico validando tamaño del prompt: %s", e, exc_info=True)
            self.session.request_active=False
            self.send_button.state(["!disabled"])
            self.cancel_button.state(["disabled"])
            self.review_mode = False  # Limpiar review_mode si falla
            self.request_types.pop(request_id, None)
            self.show_error(
                "Error interno",
                f"No se pudo validar el tamaño de la solicitud: {e}\n\nIntenta de nuevo."
            )
            return

        # Calcular tokens para UI (puede diferir de actual_tokens)
        input_tokens=max(1,(len(message)+len(selected)+len(packet))//4)
        output_tokens=self.profile.max_output_tokens
        cost=(input_tokens*self.profile.input_price_per_million+output_tokens*self.profile.output_price_per_million)/1_000_000
        last_reasons=self.context.get_last_reasons()  # Cache para no llamar en loop
        reasons=" · ".join(f"{name} ({last_reasons.get(name, 'contexto disponible')})" for name in files)
        detail=f"Contexto: {reasons or 'sin archivos'} · ~{input_tokens:,} tokens entrada"
        if cost: detail+=f" · coste máx. ~${cost:.4f}"
        self.cost_label.set(detail)
        key=tuple(files)
        if files and key not in self.approved_contexts:
            if not messagebox.askyesno("Contexto que se enviará", detail+"\n\n¿Enviar estos fragmentos al proveedor configurado?"):
                self.session.request_active=False; self.send_button.state(["!disabled"])
                self.review_mode = False  # Limpiar review_mode si se rechaza envío
                self.request_types.pop(request_id, None)
                self.activity.set("Envío cancelado."); return
            if len(self.approved_contexts) >= 128: self.approved_contexts.clear()
            self.approved_contexts.add(key)

        # Agregar mensaje a session para persistencia
        self.session.conversation.append(ChatMessage("user",message))

        # Snapshot in the UI thread: the worker must not read mutable session state.
        # IMPORTANTE: usar conversation_with_message que incluye el mensaje actual
        profile=self.profile; api_key=self.key
        self.llm.cancel_event = cancel_event
        def work():
            # Usar LLMSessionManager con error handling robusto
            # Publicar eventos en queue para thread-safety (no self.after() desde thread)
            self.llm.stream_response(
                profile, api_key, selected, packet, conversation_with_message,
                on_chunk=lambda chunk: self.ui_event_queue.put(("chunk", request_id, chunk)),
                on_error=lambda error: self.ui_event_queue.put(("error", request_id, f"No pude responder: {error}", files)),
                on_complete=lambda result, usage: self.ui_event_queue.put(("complete", request_id, result, files, usage, request_type)),
                request_id=request_id
            )
        threading.Thread(target=work,daemon=True).start()

    def finish(self, request_id: int, result: str, files: list[str], usage=(None, None), request_type: str = "normal"):
        # Verificar que este request_id sigue siendo válido
        if self.closing or request_id not in self.request_types: return
        self.request_types.pop(request_id, None)
        self.session.request_active=False; self.send_button.state(["!disabled"]); self.cancel_button.state(["disabled"]); self.session.conversation.append(ChatMessage("assistant",result)); self.activity.set("Respuesta lista." if not result.startswith("No pude") else "Revisa conexión, modelo o límites."); self.status.set("Contexto usado: "+", ".join(files) if files else "Respuesta lista.")
        if usage[0] is not None: self.cost_label.set(f"Uso real: {usage[0]:,} entrada · {usage[1] or 0:,} salida")
        # Usar request_type en lugar de self.review_mode para evitar estado persistente
        if request_type == "review":
            findings=self.parse_findings(result)
            if findings: self.show_findings(findings); return
        if self.streaming_request == request_id:
            self.streaming_request=None; self.last_response=result
        else: self.append("Articulador",result)
    def stream_chunk(self, request_id, value):
        # Verificar que este request_id sigue siendo válido (no cancelado/descartado)
        if self.closing or request_id not in self.request_types:
            return
        if self.streaming_request != request_id:
            self.streaming_request = request_id
            self.streaming_text = ""
            self.history.config(state="normal")
            self.history.insert("end", "Articulador\n", "bot")
        self.streaming_text += value
        self.history.config(state="normal")
        self.history.insert("end", value)
        self.history.see("end")
        self.history.config(state="disabled")
        self.activity.set("Articulador está respondiendo…")
    def cancel_request(self):
        if not self.session.request_active:
            return
        # Cancelar usando generation_counter (request_id actual)
        if self.cancel_event:
            self.cancel_event.set()
        self.llm.cancel(self.generation_counter)
        # Limpiar TODOS los buffers pendientes (evitar memory leak)
        self.request_types.clear()
        self.pending_chunks.clear()  # ← Limpiar chunks acumulados
        self.streaming_request = None
        self.session.request_active = False
        self.send_button.state(["!disabled"])
        self.cancel_button.state(["disabled"])
        self.activity.set("Consulta cancelada.")
        self.status.set("La respuesta tardía será descartada.")

    def process_ui_events(self):
        """Consume eventos de UI publicados por threads (thread-safe, no monopoliza UI)."""
        # Procesar máximo 100 eventos o 10ms por ciclo (evita congelación)
        events_processed = 0
        max_events_per_cycle = 100

        try:
            while events_processed < max_events_per_cycle:
                event = self.ui_event_queue.get_nowait()
                event_type = event[0]

                if event_type == "chunk":
                    # Coalescer chunks: acumular en buffer hasta complete/error
                    _, request_id, content = event
                    # Validar INMEDIATAMENTE antes de agregar a pending_chunks
                    # (chunks tardíos pueden llegar después de cancel_request)
                    if request_id not in self.request_types:
                        continue  # Descartar chunk de request cancelado

                    # Ahora es seguro agregar: request_id está confirmado como activo
                    if request_id not in self.pending_chunks:
                        self.pending_chunks[request_id] = []
                    self.pending_chunks[request_id].append(content)

                    # Procesar cada N chunks para UI responsiva
                    if len(self.pending_chunks[request_id]) >= 10:
                        coalesced = "".join(self.pending_chunks[request_id])
                        self.pending_chunks[request_id] = []
                        self.stream_chunk(request_id, coalesced)

                elif event_type == "error":
                    _, request_id, error_msg, files = event
                    # Procesar chunks pendientes antes de finalizar
                    if request_id in self.pending_chunks and self.pending_chunks[request_id]:
                        coalesced = "".join(self.pending_chunks[request_id])
                        self.stream_chunk(request_id, coalesced)
                    self.pending_chunks.pop(request_id, None)
                    self.finish(request_id, error_msg, files, (None, None), "normal")

                elif event_type == "complete":
                    _, request_id, result, files, usage, request_type = event
                    # Procesar chunks pendientes antes de finalizar
                    if request_id in self.pending_chunks and self.pending_chunks[request_id]:
                        coalesced = "".join(self.pending_chunks[request_id])
                        self.stream_chunk(request_id, coalesced)
                    self.pending_chunks.pop(request_id, None)
                    self.finish(request_id, result, files, usage, request_type)

                elif event_type == "context_failed":
                    _, request_id, error_msg = event
                    self.pending_chunks.pop(request_id, None)
                    self.context_failed(request_id, error_msg)

                elif event_type == "confirm_and_send":
                    _, request_id, message, selected, packet, files, cancel_event = event
                    self.confirm_and_send(request_id, message, selected, packet, files, cancel_event)

                events_processed += 1
        except queue.Empty:
            pass

        # Reconsumir cada 50ms (suficiente para UI responsiva, overhead bajo)
        self.after(50, self.process_ui_events)

    parse_findings = staticmethod(parse_findings)
    def show_findings(self,findings):
        show_review_dialog(self, findings)
    def undo_review(self):
        if not self.last_review_before:return
        self.editor.delete("1.0","end"); self.editor.insert("1.0",self.last_review_before); self.last_review_before=""; self.session.dirty=True; self.status.set("Último ajuste de revisión deshecho.")
    def open_document(self):
        # Cancelar cualquier solicitud activa antes de cambiar de documento
        if self.session.request_active:
            if not messagebox.askyesno("Solicitud activa", "¿Cancelar la consulta en curso?"):
                return
            self._cancel_active_request()

        # Verificar cambios sin guardar antes de abrir otro documento
        if self.session.dirty and not messagebox.askyesno("Cambios sin guardar", "¿Descartar cambios locales?"):
            return
        path=filedialog.askopenfilename(filetypes=[("Markdown", "*.md *.txt")]);
        if path:
            try: content=Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error: self.show_error("No se pudo abrir el documento",str(error)); return
            self.load_document_content(Path(path),content)
    def context_dialog(self):
        show_context_dialog(self)
    def save_document(self)->bool:
        if self.session.document_path is None:
            path=filedialog.asksaveasfilename(defaultextension=".md",filetypes=[("Markdown","*.md")]);
            if not path:return False
            self.session.document_path=Path(path)

        # Actualizar contenido desde el editor
        self.session.article = self.editor.get("1.0","end-1c")

        # Usar DocumentManager para guardado atómico con error handling
        success, error = self.docs.save_document(self.session)
        if not success:
            messagebox.showerror("Error al guardar", f"No se pudo guardar el documento: {error}")
            return False

        # Marcar como guardado y actualizar UI
        self.sync_label.config(text="● Guardado",foreground=COLORS["muted"])
        self.status.set("Artículo guardado.")
        return True
    def save_project(self):
        if self.session.dirty and not self.save_document():return
        path=filedialog.asksaveasfilename(defaultextension=".articulador.json",filetypes=[("Proyecto","*.articulador.json")]);
        if path:
            try:
                storage.save_project(self.session,Path(path))
                self.status.set("Proyecto guardado.")
            except (OSError, ValueError, RuntimeError) as error:
                messagebox.showerror(
                    "Error al guardar proyecto",
                    f"No se pudo guardar el proyecto:\n{error}\n\n"
                    f"Verifica permisos y disponibilidad de disco."
                )
                logger.error("Error guardando proyecto: %s", error, exc_info=True)
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
        try:
            data=storage.load_project(Path(path)); document=Path(data["document"])
            if not document.is_file(): raise FileNotFoundError(f"No existe el artículo del proyecto: {document}")
            article=document.read_text(encoding="utf-8")
            session=ArticleSession(document_path=document,project_path=Path(path),article=article,corpus_path=data.get("corpus"),evidence=list(data.get("evidence",[])),conversation=data.get("conversation",[]))
            self.docs.set_session(session)
            self.editor.delete("1.0","end"); self.editor.insert("1.0",self.session.article); self.history.config(state="normal"); self.history.delete("1.0","end"); self.history.config(state="disabled")
            for item in self.session.conversation:self.append("Tú" if item.role=="user" else "Articulador",item.content)
            self.status.set("Proyecto abierto.")
        except (OSError, ValueError) as error: messagebox.showerror("Proyecto no válido",str(error))
    def settings(self):
        show_settings_dialog(self)

    def _cancel_active_request(self):
        """Cancela la solicitud activa e invalida su request_id."""
        if self.cancel_event:
            self.cancel_event.set()
        # Limpiar TODOS los buffers pendientes (evitar memory leak)
        self.request_types.clear()
        self.pending_chunks.clear()  # ← Limpiar chunks acumulados
        self.streaming_request = None
        # Cancelar en LLMClient
        self.llm.cancel(self.generation_counter)
        self.session.request_active = False
        self.send_button.state(["!disabled"])
        self.cancel_button.state(["disabled"])

    def close(self):
        if self.session.dirty and not messagebox.askyesno("Cambios sin guardar","¿Cerrar sin guardar?"):return
        self.closing=True
        # Cancelar cualquier solicitud activa
        if self.session.request_active:
            self._cancel_active_request()
        self.destroy()
