from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable, Any
from tukul_ui import estilo as es
from tkinter.scrolledtext import ScrolledText

class EditorPanel(ttk.Labelframe):
    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], **kwargs) -> None:
        super().__init__(parent, text="TU ARTÍCULO", padding=es.ESP["md"], **kwargs)
        self.callbacks = callbacks
        self._build()

    def _build(self) -> None:
        self.editor = ScrolledText(self, undo=True, wrap="word", font=es.fuente(es.TIPO_LG),
                                   background=es.SUPERFICIE, padx=es.ESP["lg"], pady=es.ESP["lg"],
                                   spacing1=2, spacing2=3, spacing3=8,
                                   relief="flat", borderwidth=0,
                                   highlightthickness=1, highlightbackground=es.SUPERFICIE,
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
