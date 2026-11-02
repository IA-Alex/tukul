"""El modo foco no debe dejar sin acceso a las acciones principales.

Al activar el modo foco se ocultaba la barra completa, que era el único punto de
acceso a «Configurar modelo», «Recientes» y «Abrir proyecto». F11 era el único
atajo de salida documentado, así que quien no lo recordaba quedaba atrapado.
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from articulador_ui.app import ArticuladorApp

CLAVE = "CLAVE_PRUEBA_FOCO"


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestModoFoco(unittest.TestCase):
    """En foco la barra se oculta, pero el menú sigue disponible."""

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

    def test_en_foco_el_menu_sigue_accesible(self):
        self.app.toggle_foco()
        self.app.update()
        self.assertTrue(self.app._foco_activo)
        self.assertFalse(self.app.barra.winfo_ismapped(), "La barra debe ocultarse")
        self.assertTrue(self.app.boton_foco.winfo_ismapped(),
                        "Debe quedar un acceso al menú durante el modo foco")

    def test_el_menu_de_foco_ofrece_las_mismas_acciones(self):
        self.assertEqual(str(self.app.boton_foco.cget("menu")), str(self.app.menu_archivo))

    def test_salir_de_foco_restaura_la_barra_y_retira_el_boton(self):
        self.app.toggle_foco()
        self.app.update()
        self.app.toggle_foco()
        self.app.update()
        self.assertFalse(self.app._foco_activo)
        self.assertTrue(self.app.barra.winfo_ismapped())
        self.assertFalse(self.app.boton_foco.winfo_ismapped(),
                         "En modo normal el botón de foco no debe duplicarse")


if __name__ == "__main__":
    unittest.main()
