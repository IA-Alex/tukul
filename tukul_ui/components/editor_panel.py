from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from tukul_ui import estilo as es


class EditorPanel(ttk.Labelframe):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], **kwargs) -> None:
        super().__init__(parent, text="Tu artículo", padding=(es.ESP["md"], es.ESP["sm"], es.ESP["lg"], es.ESP["lg"]), **kwargs)
        self.callbacks = callbacks
        self._build()

    def _build(self) -> None:
        self.guia = ttk.Frame(self, style="Superficie.TFrame")
        self.guia.pack(fill="x", pady=(0, es.ESP["sm"]))
        ttk.Label(self.guia, text="Tu espacio de escritura",
                  style="PanelTitulo.TLabel").pack(anchor="w")
        ttk.Label(self.guia, text="Escribe, pega o abre un artículo para comenzar.",
                  style="PanelMeta.TLabel").pack(anchor="w", pady=(2, 0))

        self.editor = ScrolledText(self, undo=True, wrap="word", font=es.fuente(es.TIPO_LG),
                                   background=es.SUPERFICIE, padx=es.ESP["lg"] * 2,
                                   pady=es.ESP["lg"] * 2,
                                   spacing1=2, spacing2=3, spacing3=8,
                                   relief="flat", borderwidth=0,
                                   highlightthickness=1, highlightbackground=es.BORDE,
                                   highlightcolor=es.FOCO, insertbackground=es.ACENTO)
        self.editor.pack(fill="both", expand=True)

        # Eventos delegados a callbacks
        self.editor.bind("<<Modified>>", lambda e: self.callbacks["modified"]())
        self.editor.bind("<ButtonRelease-1>", lambda e: self.callbacks["update_context"]())
        self.editor.bind("<<Selection>>", lambda e: self.callbacks["update_context"]())
        self.editor.bind("<KeyRelease>", lambda e: self.callbacks["schedule_stats"]())
        self.editor.bind("<Button-3>", self.callbacks["text_menu"])

    def get_text(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def set_text(self, content: str) -> None:
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", content)
        self.editor.edit_reset()
        self.editor.edit_modified(False)

    def focus(self) -> None:
        self.editor.focus_set()
