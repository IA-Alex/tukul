from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from tukul_core import storage
from tukul_core.llm import PROVIDERS, LlmError, provider_spec, validate_endpoint
from tukul_core.logging_config import setup_logging
from tukul_core.memory import CorpusIndex, FileMemoryRepository, MemoryPolicy
from tukul_core.models import LlmProfile
from tukul_ui import estilo as es
from tukul_ui.document_scope import ReviewTarget
from tukul_ui.worker_threads import WorkerThreads, publicar_en_hilo_ui

logger = setup_logging()

# Nombres humanos: el diálogo mostraba los identificadores del dataclass.
ETIQUETAS_PERFIL = {
    "endpoint": "Endpoint",
    "model": "Modelo",
    "api_key_env": "Variable de entorno con la key",
    "max_total_model_tokens": "Límite total del modelo (tokens)",
    "max_output_tokens": "Máximo de respuesta (tokens)",
    "max_context_chars": "Máximo de contexto (caracteres)",
    "temperature": "Temperatura (de 0 a 2)",
    "input_price_per_million": "Precio entrada (por millón)",
    "output_price_per_million": "Precio salida (por millón)",
}
#: Campos imprescindibles para que el perfil responda.
CAMPOS_CONEXION = ("endpoint", "model", "api_key_env")

#: Un único mensaje para la carpeta de memoria inexistente (antes había dos
#: redacciones distintas para la misma condición; ver DF-008).
MEMORIA_NO_EXISTE = "La carpeta de artículos indicada no existe."


def _campo(frame, fila: int, name: str, variable) -> int:
    """Etiqueta humana + entrada, en la rejilla del sistema. Devuelve la fila siguiente."""
    ttk.Label(frame, text=ETIQUETAS_PERFIL[name]).grid(row=fila, column=0, sticky="w",
                                                       padx=(0, es.ESP["md"]))
    ttk.Entry(frame, textvariable=variable, width=45).grid(
        row=fila, column=1, pady=es.ESP["xs"], sticky="ew")
    if name == "api_key_env":
        # El error real observado: la etiqueta «Variable de entorno con la key»
        # comparte la palabra «key» con el campo de credencial, y la clave se
        # pegaba aquí. Se dice qué va dentro sin esperar a que falle el envío.
        ttk.Label(frame, text="Nombre de la variable, no la clave: p. ej. DEEPINFRA_API_KEY",
                  style="Tenue.TLabel", wraplength=320).grid(
            row=fila + 1, column=1, sticky="w", pady=(0, es.ESP["xs"]))
        return fila + 2
    return fila + 1


def validate_api_key_env(value: str) -> str:
    """Rechaza una clave pegada en el campo que espera un nombre de variable.

    El campo `api_key_env` se persiste en el TOML. Aceptar ahí una credencial la
    escribe en claro y además deja el perfil buscando una variable que no existe,
    con un fallo que solo aparecía al enviar el primer mensaje.
    """
    nombre = value.strip()
    if not nombre:
        return ""
    if nombre.startswith("sk-") or " " in nombre or len(nombre) > 64:
        raise LlmError(
            "«Variable de entorno con la key» espera el NOMBRE de una variable "
            "(por ejemplo DEEPINFRA_API_KEY), no la clave.\n\n"
            "La clave va en el campo «API key»."
        )
    return nombre


def _seccion(frame, fila: int, titulo: str, primera: bool = False) -> int:
    ttk.Label(frame, text=titulo, style="Tenue.TLabel").grid(
        row=fila, column=0, columnspan=2, sticky="w",
        pady=(0 if primera else es.ESP["md"], es.ESP["sm"]))
    return fila + 1


def _abrir_dialogo(app, titulo: str, *, modal: bool = True) -> tuple[tk.Toplevel, ttk.Frame]:
    """Crea un diálogo del sistema visual y devuelve (ventana, cuerpo).

    Centraliza título, padding de la rejilla y cierre con Escape, para que los
    tres diálogos no vuelvan a divergir en paddings y estilos sueltos.
    """
    dialogo = tk.Toplevel(app)
    dialogo.title(titulo)
    dialogo.transient(app)
    dialogo.configure(bg=es.FONDO)
    if modal:
        dialogo.grab_set()
    dialogo.bind("<Escape>", lambda _e: dialogo.destroy())
    cuerpo = ttk.Frame(dialogo, padding=es.ESP["lg"])
    cuerpo.pack(fill="both", expand=True)
    return dialogo, cuerpo


def _configurar_scroll(canvas: tk.Canvas, cuerpo: ttk.Frame, ventana: int) -> None:
    """Mantiene un formulario desplazable y adapta su ancho al diálogo."""
    canvas.configure(scrollregion=canvas.bbox("all"))
    canvas.itemconfigure(ventana, width=canvas.winfo_width())


def _barra_acciones(cuerpo: ttk.Frame) -> ttk.Frame:
    """Fila inferior de acciones. Una sola primaria, a la derecha.

    Se ancla abajo y hay que crearla ANTES del contenido expansible: con pack,
    lo colocado después es lo que se recorta, y los botones acababan aplastados
    a unos pocos píxeles.
    """
    barra = ttk.Frame(cuerpo)
    barra.pack(side="bottom", fill="x", pady=(es.ESP["lg"], 0))
    return barra


def _apply_suggestion(
    app,
    dialog,
    item: dict[str, str],
    review_target: ReviewTarget | None = None,
    occurrence_index: int = 0,
) -> bool:
    """Sustituye el fragmento en el editor. False si no se pudo aplicar.

    Con un ReviewTarget se aplica únicamente a la ocurrencia elegida dentro del
    texto que recibió el modelo; sin él se conserva la ruta histórica segura.
    """
    if review_target is not None:
        if not _review_scope_valida(app, review_target.scope, dialog, review_target):
            return False
        original = item["original"]
        posiciones = _ocurrencias(review_target.reviewed_text, original)
        if not posiciones:
            messagebox.showinfo(
                "Fragmento no encontrado",
                "El fragmento ya cambió o no aparece en el texto revisado.",
                parent=dialog,
            )
            return False
        if not 0 <= occurrence_index < len(posiciones):
            return False
        offset_local = posiciones[occurrence_index]
        offset_documento = review_target.start_offset + offset_local
        text = app.editor.get("1.0", "end-1c")
        if text[offset_documento:offset_documento + len(original)] != original:
            messagebox.showinfo(
                "Fragmento desactualizado",
                "El fragmento ya no coincide con el texto revisado. Vuelve a revisar el artículo.",
                parent=dialog,
            )
            return False
        app.snapshot_for_undo(text)
        inicio = app.editor.index(f"1.0 + {offset_documento} chars")
        fin = app.editor.index(f"{inicio} + {len(original)} chars")
        app.editor.delete(inicio, fin)
        app.editor.insert(inicio, item["suggestion"])
        app.session.dirty = True
        review_target.document_text = (
            text[:offset_documento] + item["suggestion"] + text[offset_documento + len(original):]
        )
        review_target.reviewed_text = (
            review_target.reviewed_text[:offset_local]
            + item["suggestion"]
            + review_target.reviewed_text[offset_local + len(original):]
        )
        return True

    text = app.editor.get("1.0", "end-1c")
    original = item["original"]
    first, last = text.find(original), text.rfind(original)
    if first < 0:
        messagebox.showinfo(
            "No encontrado", "El fragmento ya cambió o no existe.", parent=dialog
        )
        return False
    if first != last:
        messagebox.showinfo(
            "Fragmento ambiguo",
            "El texto aparece varias veces. Edita manualmente o pide una sugerencia más específica.",
            parent=dialog,
        )
        return False
    app.snapshot_for_undo(text)
    app.editor.delete("1.0", "end")
    app.editor.insert("1.0", text[:first] + item["suggestion"] + text[first + len(original):])
    app.session.dirty = True
    return True


def _reaplicar_tema_revision(app, dialog: tk.Toplevel, items: tk.Listbox, box) -> None:
    """Repinta el diálogo de revisión al cambiar de tema sin reconstruirlo.

    Gancho registrado por `show_review_dialog`: `app` se conserva solo para
    mantener la firma homogénea de los ganchos de tema.
    """
    dialog.configure(bg=es.FONDO)
    items.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                    selectbackground=es.SELECCION, selectforeground=es.TEXTO,
                    highlightbackground=es.BORDE_CONTROL, highlightcolor=es.FOCO)
    box.configure(background=es.SUPERFICIE_ALTA, foreground=es.TEXTO,
                  insertbackground=es.ACENTO, selectbackground=es.SELECCION,
                  highlightbackground=es.SUPERFICIE, highlightcolor=es.FOCO)
    box.tag_configure("rotulo", foreground=es.TEXTO_TENUE)
    app.editor.tag_configure(
        "review_source_highlight", background=es.SELECCION, foreground=es.TEXTO,
        underline=True,
    )


class _ReviewDialogController:
    """Controla selección, navegación y decisiones del diálogo de hallazgos."""

    def __init__(self, app, scope, dialog, findings, target, items, box,
                 source_label, previous, next_button, apply_button):
        self.app = app
        self.scope = scope
        self.dialog = dialog
        self.findings = findings
        self.target = target
        self.items = items
        self.box = box
        self.source_label = source_label
        self.previous = previous
        self.next_button = next_button
        self.apply_button = apply_button
        self.positions: list[int] = []
        self.match_index = 0

    def show(self, _event=None) -> None:
        """Muestra el hallazgo seleccionado y navega a su texto fuente."""
        if not self.items.curselection():
            return
        if not _review_scope_valida(self.app, self.scope, self.dialog, self.target):
            return
        item = self.findings[self.items.curselection()[0]]
        self._show_detail(item)
        self.positions = _ocurrencias(self.target.reviewed_text, item["original"])
        self.match_index = 0
        self._update_controls()
        if self.positions:
            self.update_source()
        else:
            self.app.editor.tag_remove("review_source_highlight", "1.0", "end")

    def _show_detail(self, item) -> None:
        self.box.config(state="normal")
        self.box.delete("1.0", "end")
        for label, value in (("ORIGINAL", item["original"]),
                             ("SUGERENCIA", item["suggestion"]),
                             ("MOTIVO", item["reason"])):
            self.box.insert("end", f"{label}\n", "rotulo")
            self.box.insert("end", f"{value}\n\n")
        self.box.config(state="disabled")

    def _update_controls(self) -> None:
        enabled = "normal" if self.positions else "disabled"
        multiple = "normal" if len(self.positions) > 1 else "disabled"
        self.apply_button.configure(state=enabled)
        self.previous.configure(state=multiple)
        self.next_button.configure(state=multiple)
        if not self.positions:
            self.source_label.configure(
                text="No se encontró el fragmento en el texto revisado; no se puede aplicar automáticamente."
            )
        else:
            self.source_label.configure(
                text=f"Coincidencia {self.match_index + 1} de {len(self.positions)} en el artículo"
            )

    def update_source(self) -> None:
        if not self.positions:
            return
        if not _review_scope_valida(self.app, self.scope, self.dialog, self.target):
            return
        item = self.findings[self.items.curselection()[0]]
        offset = self.target.start_offset + self.positions[self.match_index]
        start = self.app.editor.index(f"1.0 + {offset} chars")
        end = self.app.editor.index(f"{start} + {len(item['original'])} chars")
        self.app.editor.tag_remove("review_source_highlight", "1.0", "end")
        self.app.editor.tag_configure(
            "review_source_highlight", background=es.SELECCION, foreground=es.TEXTO,
            underline=True,
        )
        self.app.editor.tag_add("review_source_highlight", start, end)
        self.app.editor.see(start)
        self._update_controls()

    def move(self, delta: int) -> None:
        if not self.positions:
            return
        self.match_index = (self.match_index + delta) % len(self.positions)
        self.update_source()

    def decide(self, apply: bool) -> None:
        """Aplica o ignora el hallazgo y avanza al siguiente."""
        if not self.items.curselection():
            return
        if not _review_scope_valida(self.app, self.scope, self.dialog, self.target):
            return
        index = self.items.curselection()[0]
        if apply and not self.positions:
            return
        if apply and not _apply_suggestion(
            self.app, self.dialog, self.findings[index], self.target, self.match_index,
        ):
            return
        self.findings.pop(index)
        self.items.delete(index)
        if self.findings:
            self.items.select_set(min(index, len(self.findings) - 1))
            self.show()
        else:
            self.dialog.destroy()

    def clear_highlight(self, event=None) -> None:
        if event is not None and event.widget is not self.dialog:
            return
        try:
            self.app.editor.tag_remove("review_source_highlight", "1.0", "end")
        except tk.TclError:
            pass


def show_review_dialog(
    app,
    findings: list[dict[str, str]],
    review_target: ReviewTarget | None = None,
):
    """Muestra hallazgos anclados al documento y al texto que se revisó."""
    scope = app.scope
    if review_target is None:
        snapshot = app.editor.get("1.0", "end-1c")
        review_target = ReviewTarget(
            scope=scope,
            document_path=app.session.document_path,
            document_text=snapshot,
            reviewed_text=snapshot,
        )
    dialog, body_frame = _abrir_dialogo(app, "Revisión del artículo", modal=False)
    dialog.geometry(es.tamano_ventana(760, 520, app.winfo_screenwidth(),
                                      app.winfo_screenheight(), minimo=(620, 380)))
    dialog.minsize(620, 380)
    ttk.Label(body_frame, text="Elige un hallazgo y decide: aplicar la sugerencia o ignorarla.",
              style="Tenue.TLabel").pack(anchor="w", pady=(0, es.ESP["md"]))
    actions = _barra_acciones(body_frame)
    panes = ttk.PanedWindow(body_frame, orient="horizontal")
    panes.pack(fill="both", expand=True)
    left = ttk.Frame(panes)
    panes.add(left, weight=1)
    right = ttk.Frame(panes)
    panes.add(right, weight=2)
    items = tk.Listbox(left, exportselection=False, background=es.SUPERFICIE_ALTA,
                       foreground=es.TEXTO, selectbackground=es.SELECCION,
                       selectforeground=es.TEXTO, relief="flat", highlightthickness=1,
                       highlightbackground=es.BORDE_CONTROL, highlightcolor=es.FOCO,
                       borderwidth=0, font=es.fuente(), activestyle="none")
    scrollbar = ttk.Scrollbar(left, orient="vertical", command=items.yview)
    items.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    items.pack(side="left", fill="both", expand=True, padx=(0, es.ESP["sm"]))
    for finding in findings:
        items.insert("end", _resumen_hallazgo(finding))
    box = app._text(right, wrap="word", padx=es.ESP["md"], pady=es.ESP["sm"],
                    state="disabled")
    box.pack(fill="both", expand=True)
    box.tag_configure("rotulo", foreground=es.TEXTO_TENUE,
                      font=es.fuente(es.TIPO_SM, negrita=True))
    navigation = ttk.Frame(right)
    navigation.pack(fill="x", pady=(es.ESP["sm"], 0))
    source_label = ttk.Label(navigation, text="")
    source_label.pack(side="left", expand=True, fill="x")
    previous = ttk.Button(navigation, text="Coincidencia anterior", state="disabled")
    previous.pack(side="right", padx=(es.ESP["xs"], 0))
    next_button = ttk.Button(navigation, text="Coincidencia siguiente", state="disabled")
    next_button.pack(side="right")
    apply_button = ttk.Button(actions, text="Aplicar", style="Primaria.TButton")
    apply_button.pack(side="right")
    controller = _ReviewDialogController(
        app, scope, dialog, findings, review_target, items, box, source_label,
        previous, next_button, apply_button,
    )
    items.bind("<<ListboxSelect>>", controller.show)
    previous.configure(command=lambda: controller.move(-1))
    next_button.configure(command=lambda: controller.move(1))
    apply_button.configure(command=lambda: controller.decide(True))
    ttk.Button(actions, text="Ignorar", command=lambda: controller.decide(False)).pack(
        side="right", padx=(0, es.ESP["sm"]))
    ttk.Button(actions, text="Deshacer último", command=app.undo_review).pack(side="left")
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(
        side="left", padx=(es.ESP["sm"], 0))
    dialog.bind("<Destroy>", controller.clear_highlight, add="+")
    app._registrar_reaplicar_tema(
        dialog, lambda: _reaplicar_tema_revision(app, dialog, items, box))
    items.select_set(0)
    items.focus_set()
    controller.show()
    return dialog


def _resumen_hallazgo(item: dict[str, str]) -> str:
    """Una línea de la lista: categoría, severidad y extracto del hallazgo."""
    extract = " ".join(item["original"].split())
    if len(extract) > 44:
        extract = f"{extract[:41]}…"
    return f"{item['category'].title()} · {item['severity']} — «{extract}»"


def _review_scope_valida(
    app,
    scope,
    dialog,
    review_target: ReviewTarget | None = None,
) -> bool:
    """Comprueba que el diálogo sigue mostrando hallazgos del artículo abierto.

    Un diálogo que sobrevivió a un cambio de documento aplicaría la sugerencia
    de un artículo sobre otro, dejándolo sucio y erróneo. Devuelve True si es
    seguro aplicar y False (tras avisar y cerrar) si la revisión caducó.
    """
    if (
        app.scope is scope
        and scope.owns(app.session.document_path)
        and (review_target is None or review_target.scope is scope)
        and (review_target is None or app.editor.get("1.0", "end-1c") == review_target.document_text)
    ):
        return True
    otro_articulo = app.scope is not scope or not scope.owns(app.session.document_path)
    messagebox.showinfo(
        "Revisión caducada",
        (
            "Estos hallazgos pertenecen a otro artículo. Vuelve a revisar el actual."
            if otro_articulo
            else "El artículo cambió desde esta revisión. Vuelve a revisarlo antes de aplicar sugerencias."
        ),
        parent=dialog,
    )
    dialog.destroy()
    return False


def _ocurrencias(texto: str, fragmento: str) -> list[int]:
    """Offsets de todas las coincidencias, incluidas las que se solapan."""
    if not fragmento:
        return []
    resultado: list[int] = []
    inicio = 0
    while True:
        posicion = texto.find(fragmento, inicio)
        if posicion < 0:
            return resultado
        resultado.append(posicion)
        inicio = posicion + 1


def _bloque_credencial(frame, fila: int, key, remember) -> None:
    """API key, si se recuerda y dónde queda guardada."""
    _seccion(frame, fila, "CREDENCIAL")
    ttk.Label(frame, text="API key").grid(row=fila + 1, column=0, sticky="w",
                                          padx=(0, es.ESP["md"]))
    ttk.Entry(frame, textvariable=key, show="•", width=45).grid(
        row=fila + 1, column=1, pady=es.ESP["xs"], sticky="ew")
    ttk.Checkbutton(frame, text="Recordar en este equipo", variable=remember).grid(
        row=fila + 2, column=1, sticky="w", pady=es.ESP["xs"])
    ttk.Label(frame, text=f"Se guarda en: {storage.credential_backend()}",
              style="Tenue.TLabel", wraplength=380).grid(
        row=fila + 3, column=1, sticky="w")


def _probar_conexion(app, dialogo, nombre: str, key_var, values, *,
                     boton=None, estado=None) -> None:
    """Prueba el perfil en segundo plano y dice la causa si falla.

    Sin esto, un perfil con la clave rechazada se guardaba como válido y el
    fallo aparecía al enviar el primer mensaje, donde ya no se sabía si el
    problema era la clave, el modelo o la red. La prueba es una llamada mínima
    (un token) y solo ocurre al pulsar el botón.

    El botón se deshabilita y se anuncia «Comprobando…» mientras el worker
    corre: sin ese estado, pulsar varias veces lanzaba varias pruebas y la
    persona no veía nada hasta el final (DF-009).
    """
    try:
        perfil = _perfil_desde_formulario(nombre, values["provider"].get(), values)
    except (ValueError, LlmError) as error:
        messagebox.showerror("Configuración", str(error), parent=dialogo)
        return
    clave = key_var.get().strip() or app.session_keys.get(nombre, "") \
        or (storage.load_key(nombre) if storage.credential_backend_disponible() else "")
    if not clave:
        messagebox.showwarning(
            "Sin clave", "Escribe la API key para probar la conexión.", parent=dialogo)
        return

    def _avisar(texto: str, error: bool) -> None:
        _restaurar_boton_conexion(boton, estado)
        (messagebox.showerror if error else messagebox.showinfo)(
            "Probar conexión" if not error else "La conexión falló", texto, parent=dialogo)

    def _trabajo() -> None:
        from tukul_core.llm import LLMClient

        try:
            # Consumir el stream entero: un 401 llega al abrir y un cuerpo
            # truncado al recorrer los eventos, así que la prueba cubre ambos.
            for _chunk in LLMClient().stream(perfil, clave, "Responde solo: ok"):
                pass
            resultado = (f"El proveedor respondió correctamente.\n\nModelo: {perfil.model}",
                         False)
        except LlmError as error:
            resultado = (f"{error}\n\nRevisa la clave, el modelo y el endpoint:\n{perfil.endpoint}",
                         True)
        publicar_en_hilo_ui(app, lambda: _avisar(*resultado), logger)

    _marcar_boton_comprobando(boton, estado)
    threading.Thread(target=_trabajo, name="probar-conexion", daemon=True).start()


def _marcar_boton_comprobando(boton, estado) -> None:
    """Deshabilita el botón y muestra el estado de carga mientras se prueba."""
    if estado is not None:
        try:
            estado.config(text="Comprobando…")
        except tk.TclError:
            pass
    if boton is not None:
        try:
            boton.config(state="disabled")
        except tk.TclError:
            pass


def _restaurar_boton_conexion(boton, estado) -> None:
    """Rehabilita el botón y limpia el estado de carga al terminar la prueba."""
    if estado is not None:
        try:
            estado.config(text="")
        except tk.TclError:
            pass
    if boton is not None:
        try:
            boton.config(state="normal")
        except tk.TclError:
            pass


def _persistir_credencial(app, nombre: str, entered: str, recordar: bool) -> None:
    """Aplica la decisión sobre la API key: guardar, solo sesión, o revocar.

    Desmarcar «Recordar» debe revocar lo ya guardado; antes la credencial seguía
    en el llavero indefinidamente.
    """
    if not entered:
        app.session_keys.pop(nombre, None)
        storage.delete_key(nombre)
        return
    app._add_session_key(nombre, entered)
    if recordar:
        storage.save_key(nombre, entered)
    else:
        storage.delete_key(nombre)


def _validar_endpoint_completo(proveedor: str, endpoint: str) -> None:
    """Avisa si el endpoint es la base del proveedor en vez de la ruta de chat.

    DeepInfra publica `…/v1/openai` como base URL del SDK, y su propio `curl`
    usa `…/v1/openai/chat/completions`. Tukul habla HTTP directo: la base sola
    le obliga a adivinar la ruta. Se acepta, pero se dice qué falta.
    """
    if not endpoint or proveedor not in PROVIDERS:
        return
    esperado = provider_spec(proveedor).endpoint_hint
    if esperado and esperado != endpoint and endpoint.rstrip("/") == esperado.rsplit("/chat", 1)[0]:
        raise LlmError(
            f"El endpoint es la base del proveedor, no la ruta de chat.\n\n"
            f"Usa: {esperado}"
        )


def _perfil_desde_formulario(nombre: str, proveedor: str, values) -> LlmProfile:
    """Construye el perfil desde el formulario y valida el endpoint.

    Falla aquí y no en el primer envío: un endpoint http:// remoto mandaría la
    API key en claro y un esquema no HTTP ni siquiera es transportable.
    """
    perfil = LlmProfile(
        name=nombre,
        provider=proveedor,
        endpoint=values["endpoint"].get().strip(),
        model=values["model"].get().strip(),
        api_key_env=validate_api_key_env(values["api_key_env"].get()),
        max_total_model_tokens=int(values["max_total_model_tokens"].get()),
        max_output_tokens=int(values["max_output_tokens"].get()),
        max_context_chars=int(values["max_context_chars"].get()),
        temperature=float(values["temperature"].get()),
        input_price_per_million=float(values["input_price_per_million"].get()),
        output_price_per_million=float(values["output_price_per_million"].get()),
    )
    if perfil.endpoint:
        validate_endpoint(perfil.endpoint)
        _validar_endpoint_completo(proveedor, perfil.endpoint)
    return perfil


def show_settings_dialog(app) -> None:  # noqa: C901 (diálogo: selector + gestión de perfiles)
    """Abre el diálogo de configuración de perfiles LLM (selector + gestión)."""
    dialog, frame = _abrir_dialogo(app, "Configurar modelo")
    dialog.geometry(es.tamano_ventana(700, 620, app.winfo_screenwidth(),
                                      app.winfo_screenheight(), minimo=(560, 400)))
    dialog.minsize(560, 400)
    # Todo el cuerpo usa estilos ttk (se repintan solos); solo el fondo del
    # Toplevel es un color directo que hay que reaplicar al cambiar de tema.
    app._registrar_reaplicar_tema(dialog, lambda: dialog.configure(bg=es.FONDO))

    # Copia de trabajo: los cambios se persisten al disco solo al Guardar.
    working: dict[str, LlmProfile] = dict(app.profiles)
    selected = tk.StringVar(value=app.active_profile)

    # --- Selector y gestión de perfiles ------------------------------------
    barra_perfil = ttk.Frame(frame, style="Superficie.TFrame")
    barra_perfil.pack(fill="x", pady=(0, es.ESP["md"]))
    ttk.Label(barra_perfil, text="Perfil", style="Tenue.TLabel").pack(
        side="left", padx=(0, es.ESP["sm"]))
    selector_perfil = ttk.Combobox(barra_perfil, textvariable=selected,
                                   state="readonly", width=28)
    selector_perfil.pack(side="left", fill="x", expand=True)
    ttk.Button(barra_perfil, text="Nuevo", command=lambda: _nuevo()).pack(
        side="left", padx=(es.ESP["sm"], 0))
    ttk.Button(barra_perfil, text="Borrar", command=lambda: _borrar()).pack(
        side="left", padx=(es.ESP["xs"], 0))

    # --- Memoria local ------------------------------------------------------
    memoria = ttk.Frame(frame, style="Superficie.TFrame")
    memoria.pack(fill="x", pady=(0, es.ESP["md"]))
    ttk.Label(memoria, text="MEMORIA LOCAL", style="Tenue.TLabel").grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, es.ESP["sm"]))
    memoria.columnconfigure(1, weight=1)
    memoria_root = tk.StringVar(value=str(app.memory_root))
    memoria_estado = ttk.Label(memoria, text="Se indexa al buscar un tema.", style="Tenue.TLabel")
    ttk.Label(memoria, text="Carpeta de artículos").grid(
        row=1, column=0, sticky="w", padx=(0, es.ESP["md"]))
    ttk.Entry(memoria, textvariable=memoria_root).grid(
        row=1, column=1, sticky="ew", pady=es.ESP["xs"])

    def elegir_memoria() -> None:
        seleccionada = filedialog.askdirectory(
            parent=dialog, title="Elegir carpeta de memoria",
            initialdir=memoria_root.get() or str(Path.home()),
        )
        if seleccionada:
            memoria_root.set(seleccionada)

    def reindexar_memoria() -> None:
        raiz = Path(memoria_root.get()).expanduser()
        if not raiz.is_dir():
            messagebox.showerror("Memoria local", MEMORIA_NO_EXISTE, parent=dialog)
            return
        memoria_estado.config(text="Reindexando artículos…")

        def work() -> None:
            try:
                repository = FileMemoryRepository(
                    MemoryPolicy(root=raiz, max_file_bytes=50_000)
                )
                with CorpusIndex(app.memory_index_path) as index:
                    stats = index.refresh(repository)
                detail = (f"Índice actualizado: {stats.scanned} revisados, "
                          f"{stats.indexed} actualizados, {stats.unchanged} sin cambios.")
            except (OSError, ValueError) as error:
                detail = f"No se pudo indexar: {error}"
            publicar_en_hilo_ui(
                dialog, lambda: memoria_estado.config(text=detail), logger)

        WorkerThreads.start(work)

    ttk.Button(memoria, text="Elegir…", command=elegir_memoria).grid(
        row=1, column=2, padx=(es.ESP["sm"], 0))
    ttk.Button(memoria, text="Reindexar…", command=reindexar_memoria).grid(
        row=2, column=1, sticky="w", pady=(0, es.ESP["xs"]))
    memoria_estado.grid(row=2, column=2, sticky="w", padx=(es.ESP["sm"], 0))

    # El formulario tiene más campos que caben en una pantalla pequeña. El
    # canvas conserva todas las acciones alcanzables sin imponer una ventana
    # mínima enorme.
    host = ttk.Frame(frame)
    host.pack(fill="both", expand=True)
    canvas = tk.Canvas(host, background=es.FONDO, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    cuerpo = ttk.Frame(canvas)
    cuerpo.columnconfigure(1, weight=1)
    ventana = canvas.create_window((0, 0), window=cuerpo, anchor="nw")
    cuerpo.bind("<Configure>", lambda _event: _configurar_scroll(canvas, cuerpo, ventana))
    canvas.bind("<Configure>", lambda _event: _configurar_scroll(canvas, cuerpo, ventana))
    canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"))
    canvas.bind("<Button-4>", lambda _event: canvas.yview_scroll(-1, "units"))
    canvas.bind("<Button-5>", lambda _event: canvas.yview_scroll(1, "units"))

    fields = (
        "endpoint",
        "model",
        "api_key_env",
        "max_total_model_tokens",
        "max_output_tokens",
        "max_context_chars",
        "temperature",
        "input_price_per_million",
        "output_price_per_million",
    )

    def _perfil_seleccionado() -> LlmProfile:
        return working[selected.get()]

    profile = _perfil_seleccionado()
    provider = tk.StringVar(
        value=profile.provider if profile.provider in PROVIDERS else "openai_compatible"
    )
    values = {name: tk.StringVar(value=str(getattr(profile, name))) for name in fields}
    # La key se pinta de inmediato desde la memoria de la app (cacheada) y el
    # llavero se consulta aparte: leerlo aquí congelaba el diálogo mientras
    # D-Bus respondía. La lectura llega al widget por `after`, nunca desde el hilo.
    cacheada = app._llevero_valor(selected.get())
    key = tk.StringVar(value=cacheada)
    remember = tk.BooleanVar(value=bool(cacheada))
    _seccion(cuerpo, 0, "CONEXIÓN", primera=True)
    ttk.Label(cuerpo, text="Proveedor").grid(row=1, column=0, sticky="w",
                                             padx=(0, es.ESP["md"]))
    selector = ttk.Combobox(
        cuerpo, textvariable=provider, values=list(PROVIDERS), state="readonly", width=42
    )
    selector.grid(row=1, column=1, pady=es.ESP["xs"], sticky="ew")
    hint = ttk.Label(cuerpo, text="", style="Tenue.TLabel", wraplength=380)
    hint.grid(row=2, column=1, sticky="w", pady=(0, es.ESP["sm"]))
    previous_provider = provider.get()

    def update_provider_hint(_event=None) -> None:
        """Actualiza la pista del proveedor y su endpoint sugerido al cambiar de proveedor."""
        nonlocal previous_provider
        proveedor_actual = provider_spec(provider.get())
        old_hint = provider_spec(previous_provider).endpoint_hint
        if (
            not values["endpoint"].get().strip()
            or values["endpoint"].get().strip() == old_hint
        ):
            values["endpoint"].set(proveedor_actual.endpoint_hint)
        hint.config(
            text=f"Protocolo: {proveedor_actual.protocol}. Endpoint sugerido: {proveedor_actual.endpoint_hint}"
        )
        previous_provider = provider.get()

    selector.bind("<<ComboboxSelected>>", update_provider_hint)

    def _refrescar_perfiles() -> None:
        selector_perfil.config(values=list(working.keys()))

    def _cargar() -> None:
        p = _perfil_seleccionado()
        provider.set(p.provider if p.provider in PROVIDERS else "openai_compatible")
        for name in fields:
            values[name].set(str(getattr(p, name)))
        nombre = selected.get()
        cacheada = app._llevero_valor(nombre)
        key.set(cacheada)
        remember.set(bool(cacheada))
        update_provider_hint()
        _consultar_llavero_en_segundo_plano(nombre)

    def _consultar_llavero_en_segundo_plano(nombre: str) -> None:
        """Lee la key del perfil sin bloquear el diálogo ni tocar Tk desde el hilo.

        El hilo solo escribe la caché de la app. El repintado lo hace un sondeo
        programado DESDE el hilo de Tk al abrir el diálogo: llamar a `after`
        desde el hilo de trabajo no es seguro en Tk (lanza `RuntimeError: main
        thread is not in main loop` al registrar el callback).

        La lectura NO arranca si el dialecto de keyring ya falló: en un llavero
        sin backend (CI, contenedor) `keyring.get_password` puede tumbar el
        proceso dentro del hilo (`Fetching password with fallback` → segfault),
        no solo devolver un error.
        """
        if app._llevero_conocido(nombre) or not storage.credential_backend_disponible():
            return

        def leer() -> None:
            try:
                valor = storage.load_key(nombre)
            except storage.KeyringUnavailableError as error:
                # Llavero roto ≠ «no hay key»: no se cachea vacío (pinta una
                # pista falsa en el campo) y se deja rastro para diagnóstico.
                logger.warning("Llavero no disponible al leer '%s': %s", nombre, error)
                return
            except Exception:
                valor = ""
            app._llevero_guardar(nombre, valor)

        threading.Thread(target=leer, name=f"keyring-dialogo-{nombre}", daemon=True).start()

    def _aplicar_key_cargada() -> None:
        """Pinta la key del llavero si ya llegó y el usuario aún no escribió.

        Se programa desde el hilo de Tk (seguro) tras la primera pasada, y se
        reprograma mientras el diálogo siga abierto hasta recibir el valor.
        """
        nombre = selected.get()
        try:
            if not dialog.winfo_exists():
                return
        except tk.TclError:
            return
        if app._llevero_conocido(nombre):
            valor = app._llevero_valor(nombre)
            if not key.get():
                key.set(valor)
                remember.set(bool(valor))
            return
        try:
            dialog.after(150, _aplicar_key_cargada)
        except tk.TclError:
            pass

    def _aplicar_a_working(nombre: str) -> bool:
        """Vuelca el formulario al perfil indicado; False si el formulario es inválido."""
        try:
            working[nombre] = _perfil_desde_formulario(nombre, provider.get(), values)
        except (ValueError, LlmError) as error:
            messagebox.showerror("Configuración", str(error), parent=dialog)
            return False
        return True

    def _cambiar_perfil(_event=None) -> None:
        # Cargar el perfil recién seleccionado; las ediciones sin guardar del
        # anterior se descartan (se aplican solo al pulsar Guardar).
        _cargar()

    def _nuevo() -> None:
        nombre = simpledialog.askstring("Nuevo perfil", "Nombre del perfil:", parent=dialog)
        if not nombre or not nombre.strip():
            return
        nombre = nombre.strip()
        if nombre in working:
            messagebox.showerror("Nuevo perfil", "Ya existe un perfil con ese nombre.", parent=dialog)
            return
        working[nombre] = LlmProfile(name=nombre)
        _refrescar_perfiles()
        selected.set(nombre)
        _cargar()

    def _borrar() -> None:
        if len(working) <= 1:
            messagebox.showinfo("Borrar perfil", "No se puede borrar el único perfil.", parent=dialog)
            return
        nombre = selected.get()
        if not messagebox.askyesno("Borrar perfil", f"¿Borrar el perfil «{nombre}»?", parent=dialog):
            return
        del working[nombre]
        _refrescar_perfiles()
        selected.set(next(iter(working)))
        _cargar()

    selector_perfil.bind("<<ComboboxSelected>>", _cambiar_perfil)
    _refrescar_perfiles()
    update_provider_hint()
    # La key del llavero llega de un hilo: se aplica desde aquí, en el hilo de
    # Tk, mientras el diálogo siga abierto.
    _consultar_llavero_en_segundo_plano(selected.get())
    _aplicar_key_cargada()

    fila = 3
    for name in CAMPOS_CONEXION:
        fila = _campo(cuerpo, fila, name, values[name])
    fila = _seccion(cuerpo, fila, "LÍMITES Y COSTE")
    for name in fields:
        if name not in CAMPOS_CONEXION:
            fila = _campo(cuerpo, fila, name, values[name])
    api_key_row = fila
    _bloque_credencial(cuerpo, api_key_row, key, remember)
    fila_conexion = ttk.Frame(cuerpo)
    fila_conexion.grid(row=api_key_row + 4, column=1, sticky="w", pady=(es.ESP["sm"], 0))
    boton_conexion = ttk.Button(
        fila_conexion, text="Probar conexión…", style="Inactivo.TButton",
        command=lambda: _probar_conexion(
            app, dialog, selected.get(), key,
            {**values, "provider": provider},
            boton=boton_conexion, estado=conexion_estado),
    )
    boton_conexion.pack(side="left")
    conexion_estado = ttk.Label(fila_conexion, text="", style="Tenue.TLabel")
    conexion_estado.pack(side="left", padx=(es.ESP["sm"], 0))

    def save() -> None:
        """Persiste los perfiles editados y la credencial, y cierra el diálogo."""
        # El perfil seleccionado pasa a ser el activo; se persiste todo junto.
        active = selected.get()
        if not _aplicar_a_working(active):
            return
        nueva_memoria = Path(memoria_root.get()).expanduser()
        if not nueva_memoria.is_dir():
            messagebox.showerror(
                "Memoria local", MEMORIA_NO_EXISTE, parent=dialog
            )
            return

        # Transaccional: persistir PRIMERO, actualizar app solo si éxito.
        try:
            storage.save_profiles(working, active, app.config_path)
            app.profiles = working
            app.active_profile = active
            # Sin texto a mano: `actualizar_modelo` deriva el chip del perfil
            app.barra.actualizar_modelo()
        except (OSError, RuntimeError) as error:
            messagebox.showerror(
                "Error al guardar perfil",
                f"No se pudo guardar: {error}\n\n"
                f"Verifica permisos y disponibilidad del llavero.",
                parent=dialog
            )
            logger.error("Error guardando perfil: %s", error, exc_info=True)
            return
        # La credencial es independiente: sin llavero la key queda en sesión,
        # que es el comportamiento documentado. Un fallo aquí no invalida el
        # perfil ya guardado ni debe abrir un error modal (en CI, sin backend,
        # ese modal bloqueaba la app esperando un clic que nunca llega).
        try:
            _persistir_credencial(app, active, key.get().strip(), remember.get())
            app.memory_root = nueva_memoria.resolve()
            app.ui_state["memory_root"] = str(app.memory_root)
            controller = getattr(app, "_contexto_ctrl", None)
            if controller is not None:
                controller._memory_root = app.memory_root
            storage.save_ui_state(app._snapshot_estado_ui(), app.config_path)
            messagebox.showinfo("Configuración", "Perfil guardado.", parent=dialog)
        except (OSError, RuntimeError) as error:
            logger.warning("La key no se pudo recordar; queda solo en sesión: %s", error)
            messagebox.showinfo(
                "Perfil guardado",
                "El perfil se guardó, pero la key no se pudo recordar en este "
                f"equipo ({error}). Se usará solo durante esta sesión.",
                parent=dialog,
            )
        dialog.destroy()

    acciones = ttk.Frame(cuerpo)
    acciones.grid(row=api_key_row + 4, column=0, columnspan=2, sticky="ew",
                  pady=(es.ESP["lg"], 0))
    # Una sola acción primaria.
    ttk.Button(acciones, text="Guardar", style="Primaria.TButton",
               command=save).pack(side="right")
    ttk.Button(acciones, text="Cancelar", command=dialog.destroy).pack(
        side="right", padx=(0, es.ESP["sm"]))
    selector_perfil.focus_set()
    app._registrar_reaplicar_tema(
        dialog,
        lambda: canvas.configure(background=es.FONDO),
    )


GUIA_RAPIDA = """DE UNA IDEA A UN ARTÍCULO

1. Cuéntale a Tukul tu idea o el borrador que tienes. Pide ayuda para encontrar
   un enfoque, definir la audiencia, ordenar los puntos o ajustar el tono.
   Para empezar: «Tengo esta idea… Ayúdame a encontrar un enfoque y un esquema».

2. Reúne referencias desde el menú:
   • Buscar en Internet… busca títulos, enlaces y fragmentos con GDELT.
   • Contexto de artículos… permite buscar en tu carpeta local o añadir archivos.
   Añade solo lo que quieras usar. La búsqueda web no descarga los artículos
   completos: abre los enlaces originales para leer y verificar las fuentes.

3. Escribe o pega el borrador en el editor de la izquierda. Selecciona un
   fragmento para trabajar solo esa parte, o usa Revisar artículo para revisar
   el texto completo.

4. Guarda el artículo como Markdown o guarda un proyecto para conservar también
   la conversación.

MODELO Y PRIVACIDAD

Configura proveedor, endpoint, modelo y credencial en Configurar modelo…
Buscar en la web y en archivos locales no requiere una cuenta de modelo;
conversar sí requiere una credencial configurada. El artículo activo forma parte
de cada consulta al modelo. Las referencias que añades se autorizan al agregarlas
y se incluyen cuando conversas. Revisa la fuente original antes de confiar en
ella."""


def show_user_guide_dialog(app) -> None:
    """Muestra una guía breve accesible desde el menú de la aplicación."""
    dialog, frame = _abrir_dialogo(app, "Guía de usuario", modal=False)
    dialog.geometry(es.tamano_ventana(
        660, 540, app.winfo_screenwidth(), app.winfo_screenheight(),
        minimo=(500, 360)))
    dialog.minsize(500, 360)

    cuerpo = ttk.Frame(frame, style="Superficie.TFrame")
    cuerpo.pack(fill="both", expand=True)
    texto = tk.Text(
        cuerpo, wrap="word", background=es.SUPERFICIE_ALTA,
        foreground=es.TEXTO, insertbackground=es.TEXTO,
        padx=es.ESP["md"], pady=es.ESP["md"], relief="flat",
        font=es.fuente(),
    )
    scroll = ttk.Scrollbar(cuerpo, orient="vertical", command=texto.yview)
    texto.configure(yscrollcommand=scroll.set)
    texto.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    texto.insert("1.0", GUIA_RAPIDA)
    texto.configure(state="disabled")

    ttk.Button(frame, text="Cerrar", command=dialog.destroy).pack(
        anchor="e", pady=(es.ESP["md"], 0))
    app._registrar_reaplicar_tema(dialog, lambda: dialog.configure(bg=es.FONDO))
