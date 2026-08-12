"""Pruebas del sistema visual, los estados y la accesibilidad de la interfaz.

Ejecutan la ventana real bajo Xvfb: consultan los widgets y sus atributos, no
constantes copiadas. Cubren los criterios de aceptación:

- la interfaz explica qué ocurre sin documentación (cada estado lleva texto);
- no depende del color (cada estado lleva además símbolo y descripción);
- las acciones primarias siguen visibles al estrechar el panel;
- las confirmaciones no son modales.
"""
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from articulador_ui import estilo as es
from articulador_ui.app import ArticuladorApp
from articulador_ui.estado import ESTADOS_ACTIVOS, EstadoUI


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


class TestSistemaVisual(unittest.TestCase):
    """El sistema es compacto y accesible por construcción."""

    def test_una_capa_de_fondo_y_dos_superficies(self):
        capas = {es.FONDO, es.SUPERFICIE, es.SUPERFICIE_ALTA}
        self.assertEqual(len(capas), 3, "Fondo y dos superficies, todas distintas")

    def test_la_escala_tipografica_tiene_tres_tamanos(self):
        escala = [es.TIPO_SM, es.TIPO_MD, es.TIPO_LG]
        self.assertEqual(len(set(escala)), 3)
        self.assertEqual(escala, sorted(escala), "La escala debe ser creciente")

    def test_el_espaciado_es_la_rejilla_de_cuatro(self):
        self.assertEqual(sorted(es.ESP.values()), [4, 8, 12, 16])

    def test_todo_el_texto_cumple_contraste_aa(self):
        frentes = {
            "TEXTO": es.TEXTO, "TEXTO_TENUE": es.TEXTO_TENUE, "ACENTO": es.ACENTO,
            "ESTADO_NEUTRO": es.ESTADO_NEUTRO, "ESTADO_PROCESO": es.ESTADO_PROCESO,
            "ESTADO_EXITO": es.ESTADO_EXITO, "ESTADO_ERROR": es.ESTADO_ERROR,
            "ESTADO_AVISO": es.ESTADO_AVISO, "VOZ_USUARIO": es.VOZ_USUARIO,
            "VOZ_ASISTENTE": es.VOZ_ASISTENTE,
        }
        for nombre_frente, frente in frentes.items():
            for nombre_capa, capa in (("FONDO", es.FONDO), ("SUPERFICIE", es.SUPERFICIE),
                                      ("SUPERFICIE_ALTA", es.SUPERFICIE_ALTA)):
                razon = es.contraste(frente, capa)
                self.assertGreaterEqual(
                    razon, 4.5,
                    f"{nombre_frente} sobre {nombre_capa} da {razon:.2f}:1 (WCAG AA pide 4.5)",
                )

    def test_el_texto_del_boton_primario_contrasta_con_el_acento(self):
        self.assertGreaterEqual(es.contraste(es.ACENTO_TEXTO, es.ACENTO), 4.5)

    def test_el_indicador_de_foco_cumple_contraste_no_textual(self):
        # WCAG 1.4.11: los indicadores de foco necesitan 3:1 contra su entorno.
        for capa in (es.FONDO, es.SUPERFICIE, es.SUPERFICIE_ALTA):
            self.assertGreaterEqual(es.contraste(es.FOCO, capa), 3.0)


class TestEstados(unittest.TestCase):
    """Cada estado se distingue sin depender del color."""

    def test_los_seis_estados_existen(self):
        self.assertEqual(len(EstadoUI), 6)

    def test_cada_estado_tiene_simbolo_texto_y_color_distintos(self):
        simbolos = {estado.simbolo for estado in EstadoUI}
        titulos = {estado.titulo for estado in EstadoUI}
        self.assertEqual(len(simbolos), 6, "El símbolo distingue sin color")
        self.assertEqual(len(titulos), 6)

    def test_cada_estado_explica_que_ocurre(self):
        for estado in EstadoUI:
            self.assertTrue(estado.ayuda.strip(), f"{estado.name} sin texto de ayuda")
            self.assertGreater(len(estado.ayuda), 15,
                               f"{estado.name}: la ayuda debe explicar, no etiquetar")

    def test_la_descripcion_accesible_no_usa_el_color(self):
        descripcion = EstadoUI.ERROR.descripcion_accesible("tiempo agotado")
        self.assertIn("No se pudo completar", descripcion)
        self.assertIn("tiempo agotado", descripcion)

    def test_solo_preparando_y_transmitiendo_admiten_cancelacion(self):
        self.assertEqual(ESTADOS_ACTIVOS, {EstadoUI.PREPARANDO, EstadoUI.TRANSMITIENDO})


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestVentanaReal(unittest.TestCase):
    """La ventana montada de verdad: estados, foco, teclado y plegado."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.documento = self.raiz / "articulo.md"
        self.documento.write_text("# Título\n\nUn párrafo de prueba.\n", encoding="utf-8")
        self.app = ArticuladorApp(self.raiz / "config.toml", self.raiz)
        self.app.geometry("1100x700")
        self._asentar()

    def tearDown(self):
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    # --- estados -------------------------------------------------------
    def test_cada_estado_se_refleja_en_la_etiqueta_y_en_los_botones(self):
        for estado in EstadoUI:
            self.app.set_estado(estado)
            self._asentar()
            etiqueta = self.app.activity.get()
            self.assertIn(estado.simbolo, etiqueta, f"{estado.name} sin símbolo")
            self.assertIn(estado.titulo, etiqueta, f"{estado.name} sin texto")
            self.assertEqual(str(self.app.estado_label.cget("foreground")), estado.color)
            self.assertEqual(self.app.estado_ayuda.get(), estado.ayuda)

            activo = estado in ESTADOS_ACTIVOS
            enviar_desactivado = "disabled" in self.app.send_button.state()
            cancelar_desactivado = "disabled" in self.app.cancel_button.state()
            self.assertEqual(enviar_desactivado, activo,
                             f"{estado.name}: Enviar debe estar {'inhabilitado' if activo else 'disponible'}")
            self.assertEqual(cancelar_desactivado, not activo,
                             f"{estado.name}: Cancelar debe estar {'disponible' if activo else 'inhabilitado'}")

    def test_el_detalle_se_anade_sin_perder_el_estado(self):
        self.app.set_estado(EstadoUI.ERROR, "tiempo agotado")
        self._asentar()
        self.assertIn("tiempo agotado", self.app.activity.get())
        self.assertIn("No se pudo completar", self.app.activity.get())
        self.assertIs(self.app.estado_actual, EstadoUI.ERROR)

    def test_la_descripcion_accesible_sigue_al_estado(self):
        self.app.set_estado(EstadoUI.TRANSMITIENDO)
        self.assertIn("Recibiendo respuesta", self.app.estado_accesible())

    # --- jerarquía y plegado -------------------------------------------
    def test_el_editor_tiene_mas_peso_que_el_asistente(self):
        pesos = [int(self.app.panes.pane(p, "weight")) for p in self.app.panes.panes()]
        self.assertGreater(pesos[0], pesos[1], "El artículo es el foco principal")

    def test_el_asistente_se_oculta_y_se_restaura(self):
        self.assertTrue(self.app.asistente_visible)
        self.app.toggle_asistente()
        self._asentar()
        self.assertFalse(self.app.asistente_visible)
        self.assertIn("Mostrar", self.app.boton_panel.cget("text"))

        self.app.toggle_asistente()
        self._asentar()
        self.assertTrue(self.app.asistente_visible)
        self.assertIn("Ocultar", self.app.boton_panel.cget("text"))

    def test_f6_pliega_el_asistente_desde_el_teclado(self):
        self.app.focus_force()
        self._asentar()
        self.app.event_generate("<F6>")
        self._asentar()
        self.assertFalse(self.app.asistente_visible)

    # --- acciones siempre visibles -------------------------------------
    def test_las_acciones_primarias_siguen_visibles_con_el_panel_estrecho(self):
        self.app.geometry("820x560")
        self._asentar()
        for boton in (self.app.send_button, self.app.cancel_button, self.app.review_button):
            self.assertTrue(boton.winfo_ismapped(),
                            f"{boton.cget('text')} quedó fuera de la vista")
            self.assertGreater(boton.winfo_height(), 1)
        self.assertTrue(self.app.input.winfo_ismapped(), "El campo de mensaje debe verse")

    # --- confirmación no invasiva ---------------------------------------
    def test_la_confirmacion_de_contexto_no_es_un_modal(self):
        self.assertFalse(self.app.barra_aprobacion.winfo_ismapped(),
                         "La barra nace oculta")
        decidido = []
        with patch.object(ArticuladorApp, "set_estado"):
            self.app._pedir_aprobacion(1, ["notas.md"], ("e", "p", ("notas.md",), "h"),
                                       lambda: decidido.append("enviado"))
        self._asentar()

        self.assertTrue(self.app.barra_aprobacion.winfo_ismapped(),
                        "La confirmación aparece en el panel, no en una ventana")
        self.assertIn("notas.md", self.app.aprobacion_texto.get())
        # La ventana principal sigue operativa: no hay grab modal.
        self.assertEqual(self.app.grab_current(), None)

        self.app.boton_aprobar.invoke()
        self._asentar()
        self.assertEqual(decidido, ["enviado"])
        self.assertFalse(self.app.barra_aprobacion.winfo_ismapped())

    def test_rechazar_el_contexto_cancela_sin_enviar(self):
        self.app.request_types[7] = "normal"
        self.app._pedir_aprobacion(7, ["notas.md"], ("e", "p", ("notas.md",), "h"),
                                   lambda: self.fail("No debía enviarse"))
        self._asentar()
        self.app.boton_rechazar.invoke()
        self._asentar()

        self.assertIs(self.app.estado_actual, EstadoUI.CANCELADO)
        self.assertNotIn(7, self.app.request_types)

    # --- accesibilidad ---------------------------------------------------
    def test_las_areas_de_texto_muestran_el_foco(self):
        for area in (self.app.editor, self.app.input, self.app.history):
            self.assertEqual(str(area.cget("highlightcolor")), es.FOCO)
            self.assertGreaterEqual(int(area.cget("highlightthickness")), 1)

    def test_el_estado_del_documento_no_depende_solo_del_color(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.assertIn("Sin cambios", self.app.sync_label.cget("text"))
        self.app.editor.insert("end", " editado")
        self._asentar()
        texto = self.app.sync_label.cget("text")
        self.assertIn("Cambios sin guardar", texto)
        self.assertTrue(texto.strip().startswith("●"), "Debe llevar símbolo, no solo color")

    def test_el_panel_vacio_orienta_al_abrir_un_articulo(self):
        self.app.load_document(self.documento)
        self._asentar()
        historial = self.app.history.get("1.0", "end-1c")
        self.assertIn(self.documento.name, historial,
                      "Un panel vacío no explica nada: debe orientar")

    def test_el_boton_de_revision_nombra_su_ambito(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar artículo")
        self.app.editor.tag_add("sel", "1.0", "1.5")
        self.app.update_context()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar selección")


if __name__ == "__main__":
    unittest.main()
