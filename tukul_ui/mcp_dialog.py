"""Flujo explícito para consultar MCP y revisar el texto antes de usarlo."""

from __future__ import annotations

import json
import logging
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Protocol

from tukul_core.mcp_client import (
    McpClientError,
    McpTool,
    call_read_only_tool,
    list_read_only_tools,
)
from tukul_core.storage import save_ui_state
from tukul_ui import dialogs_base as db
from tukul_ui import estilo as es
from tukul_ui.contexto import ContextArticle
from tukul_ui.worker_threads import WorkerThreads, publicar_en_hilo_ui

logger = logging.getLogger("tukul")


class McpHost(Protocol):
    """Interfaz mínima para añadir resultados al conjunto de contexto."""

    closing: bool
    status: Any
    config_path: Path
    ui_state: dict[str, Any]

    def after(self, ms: Any, func: Any, *args: Any) -> str: ...

    def _upsert_context_article(self, article: ContextArticle) -> bool: ...

    def _authorize_context_articles(self) -> None: ...

    def _update_references_button(self) -> None: ...


def show_mcp_dialog(host: McpHost, parent: tk.Misc,  # noqa: C901 (diálogo: conexión y confirmación)
                    on_added: Any) -> None:
    """Conecta por stdio, permite consultas marcadas como lectura y revisa salida."""
    dialog, frame = db.abrir_dialogo(
        parent, "Consultar servidor MCP", modal=True, minimo=(560, 360), tamano=(680, 440))
    ttk.Label(frame, text="Servidor MCP local", style="Titulo.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Escribe el ejecutable y sus argumentos como una lista JSON. Tukul iniciará "
            "ese programa local para esta consulta. Solo aparecerán herramientas que "
            "el servidor marque como de solo lectura."
        ),
        style="TenueSuperficie.TLabel",
        wraplength=620,
        justify="left",
    ).pack(anchor="w", pady=(es.ESP["xs"], es.ESP["md"]))
    ttk.Label(frame, text="Ejecutable", style="TenueSuperficie.TLabel").pack(anchor="w")
    command = ttk.Entry(frame)
    saved = host.ui_state.get("mcp_server", {})
    if isinstance(saved, dict):
        command.insert(0, str(saved.get("command", "")))
    command.pack(fill="x", pady=(0, es.ESP["sm"]))
    ttk.Label(frame, text="Argumentos (lista JSON)", style="TenueSuperficie.TLabel").pack(anchor="w")
    args_text = ttk.Entry(frame)
    saved_args = saved.get("args", []) if isinstance(saved, dict) else []
    args_text.insert(0, json.dumps(saved_args if isinstance(saved_args, list) else []))
    args_text.pack(fill="x", pady=(0, es.ESP["md"]))
    remember = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        frame,
        text="Recordar ejecutable y argumentos en este equipo (no incluyas claves secretas)",
        variable=remember,
    ).pack(anchor="w", pady=(0, es.ESP["sm"]))
    status = ttk.Label(frame, text="La configuración solo se guarda si marcas la casilla.",
                       style="TenueSuperficie.TLabel", wraplength=620)
    status.pack(anchor="w", pady=(0, es.ESP["sm"]))

    actions = ttk.Frame(frame, style="Superficie.TFrame")
    actions.pack(side="bottom", fill="x")
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right")

    def connect() -> None:
        executable = command.get().strip()
        try:
            arguments = json.loads(args_text.get())
        except json.JSONDecodeError as error:
            messagebox.showerror(
                "Argumentos MCP", f"La lista JSON no es válida: {error}", parent=dialog)
            return
        if not executable or not isinstance(arguments, list) or not all(
            isinstance(item, str) for item in arguments
        ):
            messagebox.showerror(
                "Configuración MCP",
                "Escribe un ejecutable y una lista JSON de argumentos de texto.",
                parent=dialog,
            )
            return
        if not messagebox.askyesno(
            "Iniciar servidor MCP",
            f"Tukul ejecutará este programa local:\n\n{executable}\n"
            f"Argumentos: {json.dumps(arguments, ensure_ascii=False)}\n\n"
            "El proceso tendrá los permisos de tu usuario y podrá usar la red. "
            "Continúa solo si confías en el servidor y en su origen.",
            parent=dialog,
        ):
            return
        if remember.get():
            host.ui_state["mcp_server"] = {"command": executable, "args": arguments}
            try:
                save_ui_state(host.ui_state, host.config_path)
            except (OSError, ValueError) as error:
                messagebox.showwarning(
                    "Configuración MCP",
                    f"No se pudo guardar la configuración; se usará solo esta vez.\n\n{error}",
                    parent=dialog,
                )
        status.config(text="Conectando y leyendo las herramientas…")
        connect_button.config(state="disabled")
        host.status.set("Conectando al servidor MCP…")

        def work() -> None:
            try:
                tools = list_read_only_tools(executable, arguments)
                publicar_en_hilo_ui(
                    host,
                    lambda: show_tools(executable, arguments, tools),
                    logger,
                )
            except McpClientError as error:
                detail = str(error)
                publicar_en_hilo_ui(
                    host,
                    lambda: report_error(detail),
                    logger,
                )

        WorkerThreads.start(work)

    def report_error(detail: str) -> None:
        if not dialog.winfo_exists():
            return
        connect_button.config(state="normal")
        status.config(text="No se pudo conectar.")
        host.status.set("No se pudo conectar al servidor MCP.")
        messagebox.showerror("Servidor MCP", detail, parent=dialog)

    def show_tools(executable: str, arguments: list[str], tools: list[McpTool]) -> None:
        if not dialog.winfo_exists():
            return
        connect_button.config(state="normal")
        if not tools:
            status.config(text="El servidor no ofrece herramientas marcadas como solo lectura.")
            host.status.set("El servidor MCP no ofrece consultas de solo lectura.")
            return
        status.config(text=f"{len(tools)} herramienta(s) de solo lectura disponibles.")
        host.status.set("Servidor MCP conectado; elige una consulta.")
        show_tool_picker(host, dialog, executable, arguments, tools, on_added)

    connect_button = ttk.Button(actions, text="Conectar y listar", command=connect,
                                style="Primaria.TButton")
    connect_button.pack(side="right", padx=(0, es.ESP["sm"]))
    command.focus_set()


def show_tool_picker(host: McpHost, parent: tk.Misc, executable: str,  # noqa: C901 (diálogo: selección y llamada)
                     server_args: list[str], tools: list[McpTool],
                     on_added: Any) -> None:
    """Deja revisar descripción/esquema antes de invocar una herramienta."""
    dialog, frame = db.abrir_dialogo(
        parent, "Herramientas MCP de solo lectura", modal=True,
        minimo=(600, 420), tamano=(760, 560))
    ttk.Label(frame, text="Elige una consulta", style="Titulo.TLabel").pack(anchor="w")
    listing = db.crear_listbox(frame, height=6)
    listing.pack(fill="x", expand=False, pady=(es.ESP["sm"], es.ESP["sm"]))
    for tool in tools:
        summary = f" — {tool.description}" if tool.description else ""
        listing.insert("end", f"{tool.name}{summary}")

    ttk.Label(frame, text="Esquema de entrada", style="TenueSuperficie.TLabel").pack(anchor="w")
    schema = tk.Text(frame, height=6, wrap="word", state="disabled")
    schema.pack(fill="both", expand=True, pady=(0, es.ESP["sm"]))
    ttk.Label(frame, text="Argumentos (objeto JSON)", style="TenueSuperficie.TLabel").pack(anchor="w")
    args_entry = tk.Text(frame, height=5, wrap="word")
    args_entry.insert("1.0", "{}")
    args_entry.pack(fill="x", pady=(0, es.ESP["sm"]))
    actions = ttk.Frame(frame, style="Superficie.TFrame")
    actions.pack(fill="x")
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right")

    def choose(_event: Any = None) -> None:
        selection = listing.curselection()
        if not selection:
            return
        tool = tools[selection[0]]
        schema.configure(state="normal")
        schema.delete("1.0", "end")
        schema.insert("1.0", json.dumps(tool.input_schema, ensure_ascii=False, indent=2))
        schema.configure(state="disabled")
        args_entry.delete("1.0", "end")
        args_entry.insert("1.0", "{}")

    listing.bind("<<ListboxSelect>>", choose)

    def invoke() -> None:
        selection = listing.curselection()
        if not selection:
            messagebox.showinfo("Consulta MCP", "Selecciona una herramienta.", parent=dialog)
            return
        tool = tools[selection[0]]
        try:
            tool_arguments = json.loads(args_entry.get("1.0", "end-1c"))
        except json.JSONDecodeError as error:
            messagebox.showerror(
                "Argumentos MCP", f"El objeto JSON no es válido: {error}", parent=dialog)
            return
        if not isinstance(tool_arguments, dict):
            messagebox.showerror(
                "Argumentos MCP", "Los argumentos deben ser un objeto JSON.", parent=dialog)
            return
        if not messagebox.askyesno(
            "Confirmar consulta MCP",
            f"Consultar «{tool.name}» en el servidor local.\n\n"
            f"Argumentos:\n{json.dumps(tool_arguments, ensure_ascii=False, indent=2)}\n\n"
            "La respuesta se mostrará para revisión y todavía no se enviará al modelo.",
            parent=dialog,
        ):
            return
        invoke_button.config(state="disabled")
        host.status.set(f"Consultando MCP: {tool.name}…")

        def work() -> None:
            try:
                output = call_read_only_tool(
                    executable, server_args, tool.name, tool_arguments)
                publicar_en_hilo_ui(
                    host,
                    lambda: show_result(host, dialog, executable, tool, output, on_added),
                    logger,
                )
            except McpClientError as error:
                detail = str(error)
                publicar_en_hilo_ui(
                    host,
                    lambda: report_tool_error(dialog, invoke_button, detail),
                    logger,
                )

        WorkerThreads.start(work)

    invoke_button = ttk.Button(actions, text="Consultar herramienta…",
                               command=invoke, style="Primaria.TButton")
    invoke_button.pack(side="right", padx=(0, es.ESP["sm"]))
    if tools:
        listing.selection_set(0)
        choose()


def report_tool_error(dialog: tk.Toplevel, button: ttk.Button, detail: str) -> None:
    if dialog.winfo_exists():
        button.config(state="normal")
        messagebox.showerror("Consulta MCP", detail, parent=dialog)


def show_result(host: McpHost, parent: tk.Toplevel, executable: str,
                tool: McpTool, output: str, on_added: Any) -> None:
    """Presenta el resultado como dato no confiable y pide aprobación de contexto."""
    if not parent.winfo_exists():
        return
    host.status.set(f"Resultado MCP listo para revisar: {tool.name}.")
    dialog, frame = db.abrir_dialogo(
        parent, f"Resultado MCP: {tool.name}", modal=True,
        minimo=(600, 360), tamano=(760, 520))
    ttk.Label(frame, text=f"Resultado de {tool.name}", style="Titulo.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Revisa el contenido antes de añadirlo. La respuesta viene de un servidor "
            "externo y se tratará como material de referencia no confiable."
        ),
        style="TenueSuperficie.TLabel",
        wraplength=680,
        justify="left",
    ).pack(anchor="w", pady=(es.ESP["xs"], es.ESP["sm"]))
    output_box = tk.Text(frame, wrap="word")
    output_box.insert("1.0", output)
    output_box.configure(state="disabled")
    output_box.pack(fill="both", expand=True)
    actions = ttk.Frame(frame, style="Superficie.TFrame")
    actions.pack(fill="x", pady=(es.ESP["md"], 0))
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right")

    def add_to_context() -> None:
        label = f"MCP · {Path(executable).name} · {tool.name}"
        if not messagebox.askyesno(
            "Autorizar contexto MCP",
            "El resultado se añadirá al contexto y podrá enviarse al proveedor LLM "
            "cuando autorices el contexto. ¿Añadirlo?",
            parent=dialog,
        ):
            return
        source_id = f"mcp:{uuid.uuid4()}"
        host._upsert_context_article(ContextArticle(source_id, label, output))
        host._authorize_context_articles()
        host._update_references_button()
        on_added()
        host.status.set(f"Resultado MCP añadido al contexto: {tool.name}.")
        dialog.destroy()

    ttk.Button(actions, text="Añadir al contexto…", command=add_to_context,
               style="Primaria.TButton").pack(side="right", padx=(0, es.ESP["sm"]))
