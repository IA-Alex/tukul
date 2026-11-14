"""`WindowShell`: DPI, tamaño inicial, geometría y tema de la ventana.

Extracción DF-001 (ADR-0005, paso 2): la ventana deja de saber de geometría,
DPI y tema dentro de `TukulApp`. Estas pruebas fijan el contrato del objeto
extraído: inicialización desde el estado persistente, saneado de geometría,
restauración defensiva y validación del tema. Donde toca Tk se usa una ventana
real; el resto se prueba sin montar la aplicación completa.
"""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_ui import estilo as es
from tukul_ui import ventana
from tukul_ui.window_shell import WindowShell


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


class TestSaneadoresSinVentana(unittest.TestCase):
    """La ventana no reimplementa el saneado: delega en `window_shell`."""

    def test_geometria_saneada_delega_en_ventana(self):
        self.assertEqual(WindowShell.geometria_saneada("1x1+0+0", 1920, 1080),
                         "1120x540+0+0")
        self.assertIsNone(WindowShell.geometria_saneada(None, 1920, 1080))

    def test_ventana_expone_el_patron_compartido(self):
        self.assertIs(WindowShell.PATRON_GEOMETRIA, ventana.PATRON_GEOMETRIA)

    def test_zoom_y_recientes_delegan_en_ventana(self):
        self.assertEqual(WindowShell.zoom_validado("abc"), 1.0)
        self.assertEqual(WindowShell.zoom_validado(99), es.ZOOM_MAX)
        self.assertEqual(WindowShell.recientes_validados(["a", 3, "", "b"]), ["a", "b"])
        self.assertEqual(WindowShell.recientes_validados(None), [])

    def test_tema_validado_cae_al_oscuro(self):
        for basura in (None, "sepia", ["dark"], 7):
            self.assertEqual(WindowShell.tema_validado(basura), "dark")
        self.assertEqual(WindowShell.tema_validado("light"), "light")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestVentanaReal(unittest.TestCase):
    """Comportamiento sobre una raíz Tk real, sin construir toda la app."""

    def setUp(self):
        self.raiz = tk.Tk()

    def tearDown(self):
        try:
            self.raiz.destroy()
        except tk.TclError:
            pass

    def _shell(self, estado=None, **host_extra):
        """Monta un `WindowShell` sobre un host que registra los ajustes.

        El host envuelve la raíz Tk real pero apunta `geometry`/`minsize` para
        no depender del ciclo idle de Tk (que difiere el tamaño solicitado).
        """
        raiz = self.raiz
        for clave, valor in host_extra.items():
            setattr(raiz, clave, valor)
        raiz.tk.call("tk", "scaling", 1.0)
        self.geometrias: list[str] = []
        self.minimos: list[tuple] = []
        raiz.geometry = lambda g="": (self.geometrias.append(g) or "")  # type: ignore[method-assign]
        raiz.minsize = lambda *a: self.minimos.append(a)  # type: ignore[method-assign]
        return WindowShell(raiz, estado or {})

    def test_tema_inicial_desde_el_estado_persistente(self):
        shell = self._shell({"theme": "light"})
        self.assertEqual(shell.theme, "light")

    def test_tema_inicial_ante_estado_corrupto(self):
        shell = self._shell({"theme": ["dark"]})
        self.assertEqual(shell.theme, "dark")

    def test_aplicar_tamano_inicial_con_pantalla_utilizable(self):
        shell = self._shell()
        with patch.object(self.raiz, "winfo_screenwidth", return_value=1920), \
                patch.object(self.raiz, "winfo_screenheight", return_value=1080):
            shell.aplicar_tamano_inicial()
        self.assertEqual(self.geometrias, ["1400x864"])
        self.assertEqual(self.minimos, [(1120, 540)])

    def test_aplicar_tamano_inicial_sin_pantalla_usa_el_default(self):
        shell = self._shell()
        with patch.object(self.raiz, "winfo_screenwidth", return_value=0), \
                patch.object(self.raiz, "winfo_screenheight", return_value=0):
            shell.aplicar_tamano_inicial()
        self.assertEqual(self.geometrias, ["1180x760"])
        self.assertEqual(self.minimos, [(1120, 540)])

    def test_restaurar_geometria_ignora_estado_ausente(self):
        shell = self._shell({})
        shell.restaurar_geometria()  # no debe lanzar ni tocar la geometría
        self.assertEqual(self.geometrias, [])

    def test_restaurar_geometria_sanea_la_guardada(self):
        shell = self._shell({"geometry": "1x1+0+0"})
        with patch.object(self.raiz, "winfo_screenwidth", return_value=1920), \
                patch.object(self.raiz, "winfo_screenheight", return_value=1080):
            shell.restaurar_geometria()
        self.assertEqual(self.geometrias, ["1120x540+0+0"])

    def test_restaurar_geometria_descarta_pantalla_minuscula(self):
        shell = self._shell({"geometry": "1x1+0+0"})
        with patch.object(self.raiz, "winfo_screenwidth", return_value=50), \
                patch.object(self.raiz, "winfo_screenheight", return_value=50):
            shell.restaurar_geometria()
        self.assertEqual(self.geometrias, [])

    def test_ventana_no_mapeada_es_falsa_antes_de_pintarse(self):
        shell = self._shell()
        self.assertFalse(shell.ventana_mapeada())

    def test_ajustar_dpi_calibra_el_scaling_de_tk(self):
        shell = self._shell()
        with patch.object(self.raiz, "winfo_fpixels", return_value=144.0):
            shell.ajustar_dpi()
        self.assertAlmostEqual(float(self.raiz.tk.call("tk", "scaling")), 2.0, places=2)


class TestAjusteDeDpiSinTk(unittest.TestCase):
    """`ajustar_dpi` es best-effort: un sondeo que falla no rompe el arranque."""

    def test_sondeo_de_pantalla_que_falla_no_propaga(self):
        shell = WindowShell.__new__(WindowShell)

        class _TkFalso:
            def call(self, *a):
                raise tk.TclError("sin display")

            def splitlist(self, *a):
                raise tk.TclError("sin display")

        class HostFalso:
            tk = _TkFalso()

            def winfo_fpixels(self, _):
                raise tk.TclError("sin display")

        shell._host = HostFalso()  # type: ignore[attr-defined]
        shell.ajustar_dpi()  # no debe lanzar


class TestRestauracionIntegracion(unittest.TestCase):
    """El `TukulApp` sigue ofreciendo la API histórica (delegada)."""

    def test_app_reusa_los_saneadores_del_shell(self):
        from tukul_ui.app import TukulApp

        self.assertEqual(TukulApp._geometria_saneada("1x1+0+0", 1920, 1080),
                         WindowShell.geometria_saneada("1x1+0+0", 1920, 1080))
        self.assertEqual(TukulApp._zoom_validado("abc"), WindowShell.zoom_validado("abc"))
        self.assertEqual(TukulApp._recientes_validados(None), [])
        self.assertEqual(TukulApp._tema_validado("sepia"), "dark")
        self.assertIs(TukulApp.PATRON_GEOMETRIA, WindowShell.PATRON_GEOMETRIA)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
