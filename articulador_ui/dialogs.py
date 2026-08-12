from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from articulador_core import storage
from articulador_core.llm import PROVIDERS, LlmError, provider_spec, validate_endpoint
from articulador_core.logging_config import setup_logging
from articulador_core.models import LlmProfile
from articulador_ui import estilo as es

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


def _campo(frame, fila: int, name: str, variable) -> int:
    """Etiqueta humana + entrada, en la rejilla del sistema. Devuelve la fila siguiente."""
    ttk.Label(frame, text=ETIQUETAS_PERFIL[name]).grid(row=fila, column=0, sticky="w",
                                                       padx=(0, es.ESP["md"]))
    ttk.Entry(frame, textvariable=variable, width=45).grid(
        row=fila, column=1, pady=es.ESP["xs"], sticky="ew")
    return fila + 1


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


def _barra_acciones(cuerpo: ttk.Frame) -> ttk.Frame:
    """Fila inferior de acciones. Una sola primaria, a la derecha.

    Se ancla abajo y hay que crearla ANTES del contenido expansible: con pack,
    lo colocado después es lo que se recorta, y los botones acababan aplastados
    a unos pocos píxeles.
    """
    barra = ttk.Frame(cuerpo)
    barra.pack(side="bottom", fill="x", pady=(es.ESP["lg"], 0))
    return barra


def show_context_dialog(app) -> None:
    # Un archivo excluido deja de aparecer en las consultas siguientes, así que
    # listar solo `last_context_files` hacía la exclusión irreversible: hay que
    # ofrecer también los ya excluidos para poder volver a incluirlos.
    excluded = app.context.excluded_context
    names = sorted(set(app.scope.context_files) | set(excluded))
    if not names:
        messagebox.showinfo(
            "Contexto",
            "Envía primero una consulta para que Articulador proponga archivos relevantes.",
        )
        return

    dialogo, cuerpo = _abrir_dialogo(app, "Contexto local")
    # Única decisión del diálogo: qué archivos pueden viajar al proveedor.
    ttk.Label(cuerpo, text="Marca los archivos que pueden enviarse al proveedor.",
              style="Tenue.TLabel").pack(anchor="w", pady=(0, es.ESP["md"]))

    values = []
    for name in names:
        variable = tk.BooleanVar(value=name not in excluded)
        values.append((name, variable))
        ttk.Checkbutton(cuerpo, text=name, variable=variable).pack(anchor="w",
                                                                   pady=(0, es.ESP["xs"]))

    def aplicar() -> None:
        for name, variable in values:
            if variable.get():
                app.context.include_file(name)
            else:
                app.context.exclude_file(name)
        dialogo.destroy()

    barra = _barra_acciones(cuerpo)
    ttk.Button(barra, text="Aplicar", style="Primaria.TButton",
               command=aplicar).pack(side="right")
    ttk.Button(barra, text="Cancelar", command=dialogo.destroy).pack(
        side="right", padx=(0, es.ESP["sm"]))


def _apply_suggestion(app, dialog, item: dict[str, str]) -> bool:
    """Sustituye el fragmento en el editor. False si no se pudo aplicar.

    Solo actúa sobre coincidencias únicas: un fragmento repetido no permite saber
    cuál pretendía corregir el modelo.
    """
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


def show_review_dialog(app, findings: list[dict[str, str]]):
    """Muestra los hallazgos de una revisión. Devuelve el Toplevel creado.

    Los hallazgos se calcularon sobre un artículo concreto: el diálogo queda
    anclado al ámbito de ese documento para no aplicar un fragmento sobre otro.
    """
    scope = app.scope
    # No modal: hay que poder leer el artículo mientras se decide sobre él.
    dialog, cuerpo = _abrir_dialogo(app, "Revisión del artículo", modal=False)
    dialog.geometry("760x520")

    ttk.Label(cuerpo, text="Elige un hallazgo y decide: aplicar la sugerencia o ignorarla.",
              style="Tenue.TLabel").pack(anchor="w", pady=(0, es.ESP["md"]))

    actions = _barra_acciones(cuerpo)
    body = ttk.PanedWindow(cuerpo, orient="horizontal")
    body.pack(fill="both", expand=True)
    left = ttk.Frame(body)
    body.add(left, weight=1)
    right = ttk.Frame(body)
    body.add(right, weight=2)
    items = tk.Listbox(left, exportselection=False, background=es.SUPERFICIE_ALTA,
                       foreground=es.TEXTO, selectbackground=es.SELECCION,
                       selectforeground=es.TEXTO, highlightthickness=1,
                       highlightbackground=es.SUPERFICIE, highlightcolor=es.FOCO,
                       borderwidth=0, font=es.fuente(), activestyle="none")
    items.pack(fill="both", expand=True, padx=(0, es.ESP["sm"]))
    for item in findings:
        items.insert("end", f"{item['category'].title()} · {item['severity']}")
    box = app._text(right, wrap="word", padx=es.ESP["md"], pady=es.ESP["sm"],
                    state="disabled")
    box.pack(fill="both", expand=True)
    box.tag_configure("rotulo", foreground=es.TEXTO_TENUE,
                      font=es.fuente(es.TIPO_SM, negrita=True))

    def show(_event=None) -> None:
        if not items.curselection():
            return
        item = findings[items.curselection()[0]]
        box.config(state="normal")
        box.delete("1.0", "end")
        # Solo lo accionable: qué dice ahora, por qué cambiarlo y qué quedaría.
        for rotulo, valor in (("ORIGINAL", item["original"]),
                              ("SUGERENCIA", item["suggestion"]),
                              ("MOTIVO", item["reason"])):
            box.insert("end", f"{rotulo}\n", "rotulo")
            box.insert("end", f"{valor}\n\n")
        box.config(state="disabled")

    items.bind("<<ListboxSelect>>", show)
    items.select_set(0)
    show()

    def decide(apply: bool) -> None:
        if not items.curselection():
            return
        if apply and (app.scope is not scope or not scope.owns(app.session.document_path)):
            # Un diálogo que sobrevivió a un cambio de documento aplicaría la
            # sugerencia de un artículo sobre otro, dejándolo sucio y erróneo.
            messagebox.showinfo(
                "Revisión caducada",
                "Estos hallazgos son de otro artículo. Vuelve a revisar el actual.",
                parent=dialog,
            )
            dialog.destroy()
            return
        index = items.curselection()[0]
        if apply and not _apply_suggestion(app, dialog, findings[index]):
            return
        findings.pop(index)
        items.delete(index)
        if findings:
            items.select_set(min(index, len(findings) - 1))
            show()
        else:
            dialog.destroy()

    # Una sola acción primaria: aplicar la sugerencia elegida.
    ttk.Button(actions, text="Aplicar", style="Primaria.TButton",
               command=lambda: decide(True)).pack(side="right")
    ttk.Button(actions, text="Ignorar", command=lambda: decide(False)).pack(
        side="right", padx=(0, es.ESP["sm"]))
    ttk.Button(actions, text="Deshacer último", command=app.undo_review).pack(side="left")
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(
        side="left", padx=(es.ESP["sm"], 0))
    return dialog


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


def _persistir_credencial(app, entered: str, recordar: bool) -> None:
    """Aplica la decisión sobre la API key: guardar, solo sesión, o revocar.

    Desmarcar «Recordar» debe revocar lo ya guardado; antes la credencial seguía
    en el llavero indefinidamente.
    """
    if not entered:
        app.session_keys.pop(app.active_profile, None)
        storage.delete_key(app.active_profile)
        return
    app._add_session_key(app.active_profile, entered)
    if recordar:
        storage.save_key(app.active_profile, entered)
    else:
        storage.delete_key(app.active_profile)


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
        api_key_env=values["api_key_env"].get().strip(),
        max_total_model_tokens=int(values["max_total_model_tokens"].get()),
        max_output_tokens=int(values["max_output_tokens"].get()),
        max_context_chars=int(values["max_context_chars"].get()),
        temperature=float(values["temperature"].get()),
        input_price_per_million=float(values["input_price_per_million"].get()),
        output_price_per_million=float(values["output_price_per_million"].get()),
    )
    if perfil.endpoint:
        validate_endpoint(perfil.endpoint)
    return perfil


def show_settings_dialog(app) -> None:
    dialog, frame = _abrir_dialogo(app, "Configurar modelo")
    profile = app.profile
    provider = tk.StringVar(
        value=profile.provider if profile.provider in PROVIDERS else "openai_compatible"
    )
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
    values = {name: tk.StringVar(value=str(getattr(profile, name))) for name in fields}
    key = tk.StringVar(value=storage.load_key(app.active_profile))
    remember = tk.BooleanVar(value=bool(key.get()))
    _seccion(frame, 0, "CONEXIÓN", primera=True)
    ttk.Label(frame, text="Proveedor").grid(row=1, column=0, sticky="w",
                                            padx=(0, es.ESP["md"]))
    selector = ttk.Combobox(
        frame, textvariable=provider, values=list(PROVIDERS), state="readonly", width=42
    )
    selector.grid(row=1, column=1, pady=es.ESP["xs"], sticky="ew")
    hint = ttk.Label(frame, text="", style="Tenue.TLabel", wraplength=380)
    hint.grid(row=2, column=1, sticky="w", pady=(0, es.ESP["sm"]))
    previous_provider = provider.get()

    def update_provider_hint(_event=None) -> None:
        nonlocal previous_provider
        selected = provider_spec(provider.get())
        old_hint = provider_spec(previous_provider).endpoint_hint
        if (
            not values["endpoint"].get().strip()
            or values["endpoint"].get().strip() == old_hint
        ):
            values["endpoint"].set(selected.endpoint_hint)
        hint.config(
            text=f"Protocolo: {selected.protocol}. Endpoint sugerido: {selected.endpoint_hint}"
        )
        previous_provider = provider.get()

    selector.bind("<<ComboboxSelected>>", update_provider_hint)
    update_provider_hint()

    fila = 3
    for name in CAMPOS_CONEXION:
        fila = _campo(frame, fila, name, values[name])
    fila = _seccion(frame, fila, "LÍMITES Y COSTE")
    for name in fields:
        if name not in CAMPOS_CONEXION:
            fila = _campo(frame, fila, name, values[name])
    api_key_row = fila
    _bloque_credencial(frame, api_key_row, key, remember)
    frame.columnconfigure(1, weight=1)

    def save() -> None:
        try:
            updated = _perfil_desde_formulario(app.active_profile, provider.get(), values)
        except (ValueError, LlmError) as error:
            messagebox.showerror("Configuración", str(error), parent=dialog)
            return

        # Transaccional: persistir PRIMERO, actualizar app solo si éxito
        try:
            # 1. Guardar a disco antes de actualizar estado de app
            updated_profiles = dict(app.profiles)
            updated_profiles[app.active_profile] = updated
            storage.save_profiles(updated_profiles, app.active_profile, app.config_path)

            # 2. Si llegamos aquí, guardar fue exitoso - actualizar app
            app.profiles = updated_profiles
            app.profile_chip.config(text=f"Modelo: {updated.model or 'sin configurar'}")

            # 3. Guardar credenciales (llavero/sesión)
            _persistir_credencial(app, key.get().strip(), remember.get())

            messagebox.showinfo("Configuración", "Perfil guardado.", parent=dialog)
            dialog.destroy()
        except (OSError, RuntimeError) as error:
            messagebox.showerror(
                "Error al guardar perfil",
                f"No se pudo guardar: {error}\n\n"
                f"Verifica permisos y disponibilidad del llavero.",
                parent=dialog
            )
            logger.error("Error guardando perfil: %s", error, exc_info=True)

    acciones = ttk.Frame(frame)
    acciones.grid(row=api_key_row + 4, column=0, columnspan=2, sticky="ew",
                  pady=(es.ESP["lg"], 0))
    # Una sola acción primaria.
    ttk.Button(acciones, text="Guardar", style="Primaria.TButton",
               command=save).pack(side="right")
    ttk.Button(acciones, text="Cancelar", command=dialog.destroy).pack(
        side="right", padx=(0, es.ESP["sm"]))
