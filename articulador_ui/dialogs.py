from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from articulador_core import storage
from articulador_core.llm import PROVIDERS, LlmError, provider_spec, validate_endpoint
from articulador_core.models import LlmProfile


def show_context_dialog(app) -> None:
    # Un archivo excluido deja de aparecer en las consultas siguientes, así que
    # listar solo `last_context_files` hacía la exclusión irreversible: hay que
    # ofrecer también los ya excluidos para poder volver a incluirlos.
    excluded = app.context.excluded_context
    names = sorted(set(app.last_context_files) | set(excluded))
    if not names:
        messagebox.showinfo(
            "Contexto",
            "Envía primero una consulta para que Articulador proponga archivos relevantes.",
        )
        return
    dialog = tk.Toplevel(app)
    dialog.title("Contexto local")
    dialog.transient(app)
    dialog.grab_set()
    frame = ttk.Frame(dialog, padding=14)
    frame.pack()
    ttk.Label(frame, text="Archivos disponibles como contexto local:").pack(anchor="w")
    values = []
    for name in names:
        variable = tk.BooleanVar(value=name not in excluded)
        values.append((name, variable))
        etiqueta = name if name in app.last_context_files else f"{name}  (excluido)"
        ttk.Checkbutton(frame, text=etiqueta, variable=variable).pack(anchor="w")

    def apply() -> None:
        for name, variable in values:
            if not variable.get():
                app.context.exclude_file(name)
            else:
                app.context.include_file(name)
        dialog.destroy()

    ttk.Button(
        frame,
        text="Aplicar selección",
        style="Accent.TButton",
        command=apply,
    ).pack(anchor="e", pady=(10, 0))


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
    anclado a él para no aplicar un fragmento sobre el documento equivocado.
    """
    documento = app.session.document_path
    dialog = tk.Toplevel(app)
    dialog.title("Revisión del artículo")
    dialog.geometry("720x560")
    dialog.transient(app)
    body = ttk.PanedWindow(dialog, orient="horizontal")
    body.pack(fill="both", expand=True, padx=8, pady=8)
    left = ttk.Frame(body)
    body.add(left, weight=1)
    right = ttk.Frame(body)
    body.add(right, weight=2)
    items = tk.Listbox(left, exportselection=False)
    items.pack(fill="both", expand=True)
    for item in findings:
        items.insert("end", f"{item['category'].title()} · {item['severity']}")
    box = app._text(right, wrap="word", padx=12, pady=10, state="disabled")
    box.pack(fill="both", expand=True)

    def show(_event=None) -> None:
        if not items.curselection():
            return
        item = findings[items.curselection()[0]]
        text = (
            f"{item['category'].upper()} · {item['severity'].upper()}\n\n"
            f"Original\n{item['original']}\n\n"
            f"Sugerencia\n{item['suggestion']}\n\n"
            f"Motivo\n{item['reason']}"
        )
        box.config(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.config(state="disabled")

    items.bind("<<ListboxSelect>>", show)
    items.select_set(0)
    show()
    actions = ttk.Frame(dialog, padding=8)
    actions.pack(fill="x")

    def decide(apply: bool) -> None:
        if not items.curselection():
            return
        if apply and app.session.document_path != documento:
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

    ttk.Button(
        actions, text="Aplicar", style="Accent.TButton", command=lambda: decide(True)
    ).pack(side="right")
    ttk.Button(actions, text="Deshacer último", command=app.undo_review).pack(
        side="right", padx=(0, 6)
    )
    ttk.Button(
        actions, text="Ignorar", command=lambda: decide(False)
    ).pack(side="right", padx=(0, 6))
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="left")
    return dialog


def show_settings_dialog(app) -> None:
    dialog = tk.Toplevel(app)
    dialog.title("Configurar LLM")
    dialog.transient(app)
    dialog.grab_set()
    frame = ttk.Frame(dialog, padding=14)
    frame.pack()
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
    ttk.Label(frame, text="Proveedor").grid(row=0, column=0, sticky="w")
    selector = ttk.Combobox(
        frame, textvariable=provider, values=list(PROVIDERS), state="readonly", width=45
    )
    selector.grid(row=0, column=1, pady=3)
    hint = ttk.Label(
        frame, text="", foreground=app.COLORS["muted"], wraplength=380
    )
    hint.grid(row=1, column=1, sticky="w")
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
    for row, (name, variable) in enumerate(values.items(), start=2):
        ttk.Label(frame, text=name).grid(row=row, column=0, sticky="w")
        ttk.Entry(frame, textvariable=variable, width=48).grid(row=row, column=1, pady=3)
    # API key va en fila siguiente a los campos dinámicos
    api_key_row = 2 + len(values)
    ttk.Label(frame, text="API key").grid(row=api_key_row, column=0, sticky="w")
    ttk.Entry(frame, textvariable=key, show="•", width=48).grid(
        row=api_key_row, column=1
    )
    ttk.Checkbutton(
        frame, text="Recordar en este equipo", variable=remember
    ).grid(row=api_key_row + 1, columnspan=2, sticky="w")
    ttk.Label(
        frame,
        text=f"Almacenamiento: {storage.credential_backend()}",
        foreground=app.COLORS["muted"],
    ).grid(row=api_key_row + 2, columnspan=2, sticky="w")

    def save() -> None:
        try:
            updated = LlmProfile(
                name=app.active_profile,
                provider=provider.get(),
                endpoint=values["endpoint"].get().strip(),
                model=values["model"].get().strip(),
                api_key_env=values["api_key_env"].get().strip(),
                max_total_model_tokens=int(
                    values["max_total_model_tokens"].get()
                ),
                max_output_tokens=int(values["max_output_tokens"].get()),
                max_context_chars=int(values["max_context_chars"].get()),
                temperature=float(values["temperature"].get()),
                input_price_per_million=float(
                    values["input_price_per_million"].get()
                ),
                output_price_per_million=float(
                    values["output_price_per_million"].get()
                ),
            )
            # Fallar aquí y no en el primer envío: un endpoint http:// remoto mandaría
            # la API key en claro y un esquema no HTTP ni siquiera es transportable.
            if updated.endpoint:
                validate_endpoint(updated.endpoint)
        except (ValueError, LlmError) as error:
            messagebox.showerror(
                "Configuración", str(error), parent=dialog
            )
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
            entered = key.get().strip()
            if entered:
                app._add_session_key(app.active_profile, entered)
                if remember.get():
                    storage.save_key(app.active_profile, entered)
                else:
                    # Desmarcar «Recordar» debe revocar lo ya guardado; antes la
                    # credencial seguía en el llavero indefinidamente.
                    storage.delete_key(app.active_profile)
            else:
                app.session_keys.pop(app.active_profile, None)
                storage.delete_key(app.active_profile)

            messagebox.showinfo("Configuración", "Perfil guardado.", parent=dialog)
            dialog.destroy()
        except (OSError, RuntimeError) as error:
            messagebox.showerror(
                "Error al guardar perfil",
                f"No se pudo guardar: {error}\n\n"
                f"Verifica permisos y disponibilidad del llavero.",
                parent=dialog
            )
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Error guardando perfil: %s", error, exc_info=True)
    ttk.Button(frame, text="Guardar", style="Accent.TButton", command=save).grid(row=api_key_row+3, column=1, sticky="e", pady=8)
