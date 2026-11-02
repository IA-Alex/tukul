"""Una sola petición viva a la vez.

Dos envíos simultáneos (p. ej. pulsar Enviar y «Revisar artículo» en rápida
sucesión, o dos `request()` seguidos) reutilizaban la misma ventana de estado:
la respuesta del primero se pintaba sobre la segunda petición y la segunda
quedaba sin dueño. `send_message()` ya se protegía; `review()` y cualquier
llamada directa a `request()` no.
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_ui.app import TukulApp

CLAVE = "CLAVE_PRUEBA_REENTRADA"


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestReentradaDePeticiones(unittest.TestCase):
    """La guarda de `request()` no debe dejar entrar una segunda petición."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.documento = self.raiz / "articulo.md"
        self.documento.write_text("La introducción es floja.", encoding="utf-8")
        config = self.raiz / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\n'
            'endpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "' + CLAVE + '"\n',
            encoding="utf-8")
        os.environ[CLAVE] = "clave"
        self.app = TukulApp(config)
        self.app.load_document(self.documento)
        self._asentar()

    def tearDown(self):
        self.app.destroy()
        self.directorio.cleanup()
        os.environ.pop(CLAVE, None)

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_segunda_peticion_no_reemplaza_a_la_primera(self):
        """Con una petición viva, otra `request()` no incrementa el contador."""
        self.app.session.request_active = True
        generacion = self.app.generation_counter
        with patch.object(self.app, "confirm_and_send") as enviar:
            self.app.request("segundo mensaje")
            self.app.update()
        enviar.assert_not_called()
        self.assertEqual(self.app.generation_counter, generacion,
                         "La petición rechazada no debe asignar un request_id nuevo")

    def test_tras_cancelar_se_puede_volver_a_enviar(self):
        """La guarda no deja bloqueada la interfaz: cancelar libera el envío."""
        self.app.session.request_active = True
        self.app.cancel_request()
        self._asentar()
        self.assertFalse(self.app.session.request_active)
        with patch.object(self.app, "confirm_and_send") as enviar:
            self.app.request("mensaje nuevo")
            self.app.update()
        enviar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
