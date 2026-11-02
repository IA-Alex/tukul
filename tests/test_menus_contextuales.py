"""Los menús contextuales no se acumulan.

Cada clic derecho creaba un `tk.Menu` hijo de la ventana raíz y nunca lo
destruía, así que la sesión ganaba un widget Tk por clic. Los menús se crean
bajo demanda (a diferencia del menú de la barra, `menu_archivo`), por eso deben
destruirse al cerrarse.
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from articulador_ui.app import ArticuladorApp

CLAVE = "CLAVE_PRUEBA_MENUS"


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


def _menus(widget) -> list[tk.Menu]:
    """Menús hijos directos del widget indicado."""
    try:
        hijos = widget.winfo_children()
    except tk.TclError:
        return []
    return [hijo for hijo in hijos if isinstance(hijo, tk.Menu)]


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestMenusContextuales(unittest.TestCase):
    """Abrir N menús no debe dejar N widgets vivos."""

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
        self.app = ArticuladorApp(config)
        self.app.load_document(documento)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.directorio.cleanup()
        os.environ.pop(CLAVE, None)

    def _clic_derecho(self, manejador, widget) -> None:
        """Simula un clic derecho cerrando el menú inmediatamente (Tk lo bloquea)."""
        evento = tk.Event()
        evento.widget = widget
        evento.x_root = widget.winfo_rootx() + 5
        evento.y_root = widget.winfo_rooty() + 5
        # `tk_popup` no retorna hasta cerrar el menú: se sustituye por un no-op y
        # se comprueba que el flujo llega a destruirlo igualmente.
        with patch.object(tk.Menu, "tk_popup", return_value=None):
            manejador(evento)

    def test_abrir_varios_menus_de_edicion_no_deja_widgets(self):
        antes = len(_menus(self.app))
        for _ in range(5):
            self._clic_derecho(self.app.text_menu, self.app.editor)
        despues = len(_menus(self.app))
        self.assertEqual(despues, antes,
                         f"Quedaron {despues - antes} menús sin destruir")

    def test_abrir_varios_menus_del_historial_no_deja_widgets(self):
        antes = len(_menus(self.app))
        for _ in range(5):
            self._clic_derecho(self.app.history_menu, self.app.history)
        despues = len(_menus(self.app))
        self.assertEqual(despues, antes,
                         f"Quedaron {despues - antes} menús sin destruir")

    def test_el_menu_se_destruye_aunque_tk_popup_falle(self):
        """Un error al mostrar el menú tampoco debe dejar el widget vivo."""
        evento = tk.Event()
        evento.widget = self.app.editor
        evento.x_root = evento.y_root = 0
        antes = len(_menus(self.app))
        with patch.object(tk.Menu, "tk_popup", side_effect=tk.TclError("boom")):
            with self.assertRaises(tk.TclError):
                self.app.text_menu(evento)
        self.assertEqual(len(_menus(self.app)), antes)


if __name__ == "__main__":
    unittest.main()
