"""Ayudantes compartidos por las regresiones de auditoría.

Extraídos de `test_auditoria_regresion.py` al dividirlo por dominio, para no
duplicarlos ni depender de importar un archivo de pruebas desde otro.
"""
from __future__ import annotations

import queue
import time
import tkinter as tk
from unittest.mock import Mock

from tukul_core.models import ArticleSession
from tukul_ui.app import TukulApp
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import EstadoUI


def _esperar_hilo_de_envio(app: TukulApp, desde: int = 0, timeout: float = 5.0) -> None:
    """Espera a que el hilo daemon de `confirm_and_send` invoque `app.llm.stream_response`.

    `confirm_and_send()` lanza un hilo real; mantener el parche activo hasta
    `tearDown` no basta si el hilo ni siquiera ha empezado a ejecutarse cuando
    el test termina. Sin esta espera, ese hilo puede seguir sin arrancar
    minutos después —bajo la carga de la suite completa— y aparecer en medio
    de un test totalmente distinto, colisionando con Tk desde otro hilo.

    El límite se subió de 2.0s a 5.0s: 2s resultaba insuficiente en algunas
    ejecuciones bajo cobertura (`--cov`) con la suite completa ya corrida en
    el mismo proceso. Sigue habiendo un caso residual —solo reproducido con
    `--cov` + `--junitxml` + los 221 tests juntos, nunca en aislamiento— donde
    la espera se agota igualmente; ver la nota de la auditoría 2026-08-21 en
    el historial de commits antes de subir este número de nuevo: no parece
    ser una cuestión de cuánto se espera, sino de orden/composición de la
    suite, y merece su propia investigación en vez de un timeout mayor.

    `desde` es el `call_count` antes de invocar `confirm_and_send`: un mismo
    test puede enviar varias veces sobre el mismo mock, así que comprobar solo
    `.called` no distinguiría un envío nuevo de uno anterior ya resuelto.
    """
    mock_obj = app.llm.stream_response
    limite = time.monotonic() + timeout
    while mock_obj.call_count <= desde and time.monotonic() < limite:
        app.update()
        time.sleep(0.01)
    assert mock_obj.call_count > desde, "El hilo de confirm_and_send no invocó el mock a tiempo"


class _Var:
    """StringVar mínimo: los ayudantes sin ventana no tienen raíz Tk."""

    def __init__(self, valor: str = "") -> None:
        self._valor = valor

    def set(self, valor) -> None:
        self._valor = valor

    def get(self):
        return self._valor


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


HAS_DISPLAY = _display_available()


def _headless_app() -> TukulApp:
    """App con el estado mínimo de una petición, sin construir widgets reales."""
    app = TukulApp.__new__(TukulApp)
    app.closing = False
    app.control_queue = queue.Queue()
    app.chunks = ChunkBuffer()
    app.request_types = {}
    app.streaming_request = None
    app.streaming_text = ""
    app.scope = DocumentScope()
    app.estado_actual = EstadoUI.REPOSO
    app.activity_var = _Var(EstadoUI.REPOSO.etiqueta())
    app.estado_ayuda_var = _Var(EstadoUI.REPOSO.ayuda)
    app.estado_label = Mock()
    app.history = Mock()
    app.activity_var = Mock()
    app.status = Mock()
    app.cost_label_var = Mock()
    app.send_button = Mock()
    app.cancel_button = Mock()
    app.after = Mock()
    app.stream_chunk = Mock()
    app.docs = Mock()
    app.docs.session = ArticleSession()
    return app
