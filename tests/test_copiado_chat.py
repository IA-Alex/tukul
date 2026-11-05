"""Copiado de mensajes del chat: cada mensaje se copia entero y por separado.

Defecto observado en la interfaz: «Copiar mensaje» devolvía siempre el primero
del historial con esa etiqueta. `tag_nextrange`/`tag_prevrange` no devuelven el
rango que contiene la posición, sino el primero o el último de la etiqueta, así
que con varios mensajes del mismo tipo el copiado mostraba el incorrecto.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tkinter as tk

from tukul_ui.app import TukulApp


def _hay_display() -> bool:
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_hay_display(), "requiere un servidor X")
class TestCopiadoDeMensajes(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.id().replace(".", "_"))
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.app = TukulApp(Path(self._tmp.name) / "config.toml")
        self.app.update()
        self.app.history.config(state="normal")
        self.app.history.delete("1.0", "end")
        self.app.history.config(state="disabled")
        self.app.append("Tukul", "Primera respuesta.")
        self.app.append("Tú", "Segunda pregunta.")
        self.app.append("Tukul", "Tercera respuesta.")
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self._tmp.cleanup()

    def _copiado(self, indice):
        rango = self.app._rango_del_mensaje(indice)
        return self.app.history.get(*rango).strip() if rango else None

    def test_cada_mensaje_se_copia_por_separado(self):
        self.assertEqual(self._copiado("2.0"), "Primera respuesta.")
        self.assertEqual(self._copiado("5.0"), "Segunda pregunta.")
        self.assertEqual(self._copiado("8.0"), "Tercera respuesta.")

    def test_los_rotulos_no_son_mensajes(self):
        for indice in ("1.0", "4.0", "7.0"):
            self.assertIsNone(self._copiado(indice))

    def test_copiar_un_mensaje_del_medio_no_devuelve_el_primero(self):
        self.app.history.mark_set("insert", "5.0")
        self.app._copiar_mensaje_en_cursor()
        self.assertEqual(self.app.clipboard_get(), "Segunda pregunta.")


if __name__ == "__main__":
    unittest.main()
