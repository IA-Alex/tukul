"""Tests de ToolTip contra un servidor X real (Xvfb en CI/quality-gate)."""
import tkinter as tk
import unittest

from articulador_ui.tooltip import ToolTip


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


HAS_DISPLAY = _display_available()


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class ToolTipTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.widget = tk.Button(self.root, text="botón")
        self.widget.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def _tooltip(self, texto: str = "pista") -> ToolTip:
        return ToolTip(self.widget, texto, demora=500)

    def test_mostrar_crea_una_ventana_con_el_texto(self):
        tip = self._tooltip("Abrir artículo (Ctrl+O)")

        tip._mostrar()

        self.assertIsNotNone(tip._ventana)
        etiquetas = [w for w in tip._ventana.winfo_children() if isinstance(w, tk.Label)]
        self.assertEqual(len(etiquetas), 1)
        self.assertEqual(etiquetas[0].cget("text"), "Abrir artículo (Ctrl+O)")

    def test_mostrar_no_hace_nada_si_el_widget_no_esta_mapeado(self):
        oculto = tk.Button(self.root, text="oculto")  # nunca se empaqueta
        tip = ToolTip(oculto, "no debería verse")

        tip._mostrar()

        self.assertIsNone(tip._ventana)

    def test_ocultar_destruye_la_ventana_y_libera_el_activo(self):
        tip = self._tooltip()
        tip._mostrar()

        tip._ocultar()

        self.assertIsNone(tip._ventana)
        self.assertIsNone(ToolTip._activo)

    def test_solo_un_tooltip_activo_a_la_vez(self):
        primero = self._tooltip("primero")
        segundo_widget = tk.Button(self.root, text="otro")
        segundo_widget.pack()
        self.root.update()
        segundo = ToolTip(segundo_widget, "segundo")

        primero._mostrar()
        self.assertIsNotNone(primero._ventana)

        segundo._mostrar()

        self.assertIsNone(primero._ventana, "El primero debe ocultarse al mostrar el segundo")
        self.assertIsNotNone(segundo._ventana)

    def test_programar_y_cancelar_no_deja_el_after_vivo(self):
        tip = self._tooltip()
        tip._programar()
        self.assertIsNotNone(tip._id)

        tip._cancelar()

        self.assertIsNone(tip._id)

    def test_evento_leave_oculta_una_tooltip_visible(self):
        tip = self._tooltip()
        tip._mostrar()

        tip._ocultar(None)

        self.assertIsNone(tip._ventana)

    def test_set_texto_actualiza_la_etiqueta_visible(self):
        tip = self._tooltip("original")
        tip._mostrar()

        tip.set_texto("actualizado")

        etiqueta = next(w for w in tip._ventana.winfo_children() if isinstance(w, tk.Label))
        self.assertEqual(etiqueta.cget("text"), "actualizado")
        self.assertEqual(tip.texto, "actualizado")

    def test_no_muestra_la_pista_de_fondo_sobre_un_dialogo_modal(self):
        """Un modal tapa la ventana: su pista no debe quedar por encima."""
        dialogo = tk.Toplevel(self.root)
        entrada = tk.Entry(dialogo)
        entrada.pack()
        dialogo.grab_set()
        self.root.update()
        tip = self._tooltip("Pista de un control de la ventana principal")

        tip._mostrar()

        self.assertIsNone(tip._ventana, "La pista de la ventana de fondo no debe aparecer")
        dialogo.grab_release()
        dialogo.destroy()

    def test_muestra_la_pista_del_control_del_propio_dialogo(self):
        """Dentro del modal, la pista de un control suyo sí es útil."""
        dialogo = tk.Toplevel(self.root)
        entrada = tk.Entry(dialogo)
        entrada.pack()
        dialogo.grab_set()
        self.root.update()
        tip = ToolTip(entrada, "pista del diálogo")

        tip._mostrar()

        self.assertIsNotNone(tip._ventana)
        dialogo.grab_release()
        dialogo.destroy()

    def test_set_texto_sin_ventana_visible_solo_guarda_el_valor(self):
        tip = self._tooltip("original")

        tip.set_texto("nuevo, sin mostrarse todavía")

        self.assertIsNone(tip._ventana)
        self.assertEqual(tip.texto, "nuevo, sin mostrarse todavía")
        tip._mostrar()
        etiqueta = next(w for w in tip._ventana.winfo_children() if isinstance(w, tk.Label))
        self.assertEqual(etiqueta.cget("text"), "nuevo, sin mostrarse todavía")

    def test_ocultar_tras_destruir_el_widget_no_lanza(self):
        tip = self._tooltip()
        tip._mostrar()
        tip._ventana.destroy()  # simula que Tk ya la tiró (p. ej. cierre de la app)

        tip._ocultar()  # no debe propagar TclError

        self.assertIsNone(tip._ventana)


if __name__ == "__main__":
    unittest.main()
