"""Pruebas del botón «Limpiar» del panel del asistente (Task 1)."""

import tkinter as tk

import pytest

from tukul_ui.components.assistant_panel import AssistantPanel


@pytest.fixture
def panel():
    root = tk.Tk()
    llamadas: list[str] = []
    callbacks = {
        "send_message": lambda: None,
        "cancel_request": lambda: None,
        "review": lambda: None,
        "clear_history": lambda: llamadas.append("clear"),
        "create_input": lambda parent: tk.Text(parent, height=3),
        "create_history": lambda parent: tk.Text(parent),
    }
    p = AssistantPanel(root, callbacks)
    yield p, llamadas
    root.destroy()


def test_el_boton_limpiar_invoca_el_callback(panel):
    p, llamadas = panel
    p.clear_button.invoke()
    assert llamadas == ["clear"]


def test_el_boton_limpiar_se_deshabilita_sin_conversacion(panel):
    p, _ = panel
    p.set_clear_enabled(False)
    assert str(p.clear_button["state"]) == "disabled"
    p.set_clear_enabled(True)
    assert str(p.clear_button["state"]) == "normal"
