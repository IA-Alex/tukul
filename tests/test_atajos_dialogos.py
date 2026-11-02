"""Los atajos globales no deben actuar desde dentro de un diálogo.

`bind_all` registra los atajos en toda la aplicación, incluida la ventana de un
diálogo abierto encima. Antes, con «Configurar modelo» abierto, `Ctrl+S` guardaba
el artículo y `Ctrl+O` lanzaba el selector de archivos por debajo del modal.
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_ui.app import TukulApp

CLAVE = "CLAVE_PRUEBA_ATAJOS"


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestAtajosFrenteADialogos(unittest.TestCase):
    """Un atajo nace en la ventana que tiene el foco; la principal solo manda."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        raiz = Path(self.directorio.name)
        documento = raiz / "articulo.md"
        documento.write_text("texto", encoding="utf-8")
        config = raiz / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\n'
            'endpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "' + CLAVE + '"\n',
            encoding="utf-8")
        os.environ[CLAVE] = "clave"
        self.app = TukulApp(config)
        self.app.load_document(documento)
        for _ in range(3):
            self.app.update()
        self.dialogo = tk.Toplevel(self.app)
        self.dialogo.grab_set()
        self.entrada = tk.Entry(self.dialogo)
        self.entrada.pack()
        self.app.update()

    def tearDown(self):
        self.dialogo.destroy()
        self.app.destroy()
        self.directorio.cleanup()
        os.environ.pop(CLAVE, None)

    def _evento(self, widget) -> object:
        """Evento mínimo con el widget de origen, como el que pasa Tk."""
        evento = tk.Event()
        evento.widget = widget
        self.assertTrue(hasattr(evento, "widget"))
        return evento

    def test_ctrl_s_desde_el_dialogo_no_guarda(self):
        with patch.object(self.app, "save_document") as guardar:
            manejador = self.app._manejador_atajo(self.app.save_document)
            resultado = manejador(self._evento(self.entrada))
        guardar.assert_not_called()
        self.assertEqual(resultado, "", "El evento se deja pasar al diálogo, no se traga")

    def test_ctrl_s_desde_la_ventana_principal_si_guarda(self):
        with patch.object(self.app, "save_document") as guardar:
            # El manejador debe crearse DESPUÉS del parche: si se captura antes,
            # envuelve el método real y el mock nunca se invoca.
            manejador = self.app._manejador_atajo(self.app.save_document)
            resultado = manejador(self._evento(self.app.editor))
        guardar.assert_called_once()
        self.assertEqual(resultado, "break")

    def test_el_atajo_real_no_dispara_desde_un_widget_del_dialogo(self):
        """Prueba de integración: el binding `bind_all` real respeta el diálogo."""
        with patch.object(self.app, "save_document") as guardar:
            self.entrada.focus_force()
            self.app.update()
            self.entrada.event_generate("<Control-s>")
            self.app.update()
        guardar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
