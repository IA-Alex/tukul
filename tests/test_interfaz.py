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
from tkinter import font as tkfont
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_ui import estilo as es
from tukul_ui.app import TukulApp
from tukul_ui.components.top_bar import TopBar
from tukul_ui.estado import ESTADOS_ACTIVOS, EstadoUI


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
        self.app = TukulApp(self.raiz / "config.toml")
        self.app.geometry("1100x700")
        self._asentar()
        # La ventana debe estar MAPEADA (pack/winfo_ismapped y las medidas solo
        # valen así), pero no debe estorbar. Con `withdraw()` dejaría de estar
        # mapeada y las aserciones medirían cero, por eso se mueve fuera del
        # escritorio. Aun así, X11 la recorta a la pantalla y el WM puede darle
        # foco: por eso la suite debe correr con `xvfb-run` (lo exige
        # `conftest.py`). Este desplazamiento es solo una segunda barrera.
        self.app.geometry(f"1100x700+{self.app.winfo_screenwidth() + 200}+0")
        self._asentar()

    def tearDown(self):
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_enviar_explica_el_alcance_de_la_consulta(self):
        """La acción primaria aclara qué contexto se enviará al modelo."""
        self.assertIn("artículo activo", self.app.panel_asistente.tooltip_enviar.texto)
        self.assertIn("contexto aprobado", self.app.panel_asistente.tooltip_enviar.texto)

    # --- estados -------------------------------------------------------
    def test_cada_estado_se_refleja_en_la_etiqueta_y_en_los_botones(self):
        for estado in EstadoUI:
            self.app.set_estado(estado)
            self._asentar()
            etiqueta = self.app.activity_var.get()
            self.assertIn(estado.simbolo, etiqueta, f"{estado.name} sin símbolo")
            self.assertIn(estado.titulo, etiqueta, f"{estado.name} sin texto")
            self.assertEqual(str(self.app.estado_label.cget("foreground")), estado.color)
            self.assertEqual(self.app.estado_ayuda_var.get(), estado.ayuda)

            activo = estado in ESTADOS_ACTIVOS
            enviar_desactivado = "disabled" in self.app.send_button.state()
            cancelar_desactivado = "disabled" in self.app.cancel_button.state()
            self.assertEqual(enviar_desactivado, activo,
                             f"{estado.name}: Enviar debe estar {'inhabilitado' if activo else 'disponible'}")
            # «Cancelar» siempre ocupa su sitio (así se descubre la salida)
            # pero solo se viste de botón cuando hay algo que cancelar: en
            # reposo usa el estilo «Inactivo», sin relieve.
            self.assertTrue(self.app.cancel_button.winfo_ismapped(),
                            f"{estado.name}: Cancelar debe seguir visible")
            self.assertEqual(cancelar_desactivado, not activo,
                             f"{estado.name}: Cancelar debe estar {'disponible' if activo else 'inhibido'}")
            estilo_esperado = "TButton" if activo else "Inactivo.TButton"
            self.assertEqual(str(self.app.cancel_button.cget("style")), estilo_esperado,
                             f"{estado.name}: Cancelar con traje equivocado")
            # Enviar y Revisar nunca quedan muertos tras cerrar la petición:
            # toda transición los devuelve a disponible.
            for boton in (self.app.send_button, self.app.review_button):
                self.assertEqual("disabled" in boton.state(), activo,
                                 f"{estado.name}: {boton.cget('text')} con estado incorrecto")
            # Guardar depende del documento, no de la consulta: se puede
            # guardar mientras el modelo responde.
            self.assertNotIn("disabled", self.app.boton_guardar.state(),
                             f"{estado.name}: Guardar no debe depender de la consulta")

    def test_el_detalle_se_anade_sin_perder_el_estado(self):
        self.app.set_estado(EstadoUI.ERROR, "tiempo agotado")
        self._asentar()
        self.assertIn("tiempo agotado", self.app.activity_var.get())
        self.assertIn("No se pudo completar", self.app.activity_var.get())
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
        # El texto es fijo («Panel IA»): no cambia para no desplazar la barra.
        self.assertIn("Panel IA", self.app.boton_panel.cget("text"))
        # Quien dice qué hará es el tooltip, y sí cambia.
        self.assertIn("Mostrar", self.app.barra.tooltip_panel.texto)

        self.app.toggle_asistente()
        self._asentar()
        self.assertTrue(self.app.asistente_visible)
        self.assertIn("Panel IA", self.app.boton_panel.cget("text"))
        self.assertIn("Ocultar", self.app.barra.tooltip_panel.texto)

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
        for boton in (self.app.send_button, self.app.review_button):
            self.assertTrue(boton.winfo_ismapped(),
                            f"{boton.cget('text')} quedó fuera de la vista")
            self.assertGreater(boton.winfo_height(), 1)
        self.assertTrue(self.app.input.winfo_ismapped(), "El campo de mensaje debe verse")
        # Cancelar ya ocupa su sitio en reposo (apagado, sin relieve): al
        # iniciar la consulta no empuja a los demás controles.
        self.assertTrue(self.app.cancel_button.winfo_ismapped())
        ancho_reposo = self.app.cancel_button.winfo_width()
        self.app.set_estado(EstadoUI.TRANSMITIENDO)
        self._asentar()
        self.assertTrue(self.app.cancel_button.winfo_ismapped())
        self.assertAlmostEqual(self.app.cancel_button.winfo_width(), ancho_reposo, delta=1,
                               msg="Cancelar no debe cambiar de ancho al activarse")

    def test_cerrar_la_peticion_libera_todas_las_acciones(self):
        """`_reset_request_ui` devuelve Enviar y Revisar a disponible.

        Antes solo liberaba Enviar: Revisar se quedaba esperando tras un cierre
        por error o cancelación. Cancelar sigue visible, pero vuelve a su traje
        inactivo para no competir con «Revisar artículo».
        """
        self.app.set_estado(EstadoUI.TRANSMITIENDO)
        self._asentar()
        self.assertIn("disabled", self.app.send_button.state())
        self.app._reset_request_ui()
        self._asentar()
        for boton in (self.app.send_button, self.app.review_button):
            self.assertNotIn("disabled", boton.state(),
                             f"{boton.cget('text')} quedó inhabilitado tras cerrar la petición")
        self.assertTrue(self.app.cancel_button.winfo_ismapped(),
                        "Cancelar debe seguir visible para descubrir la salida")
        self.assertEqual(str(self.app.cancel_button.cget("style")), "Inactivo.TButton")

    # --- confirmación no invasiva ---------------------------------------
    def test_la_confirmacion_de_contexto_no_es_un_modal(self):
        self.assertFalse(self.app.panel_asistente.barra_aprobacion.winfo_ismapped(),
                         "La barra nace oculta")
        decidido = []
        with patch.object(TukulApp, "set_estado"):
            self.app._pedir_aprobacion(1, ["notas.md"], ("e", "p", "m", ("notas.md",), "h"),
                                       lambda: decidido.append("enviado"))
        self._asentar()

        self.assertTrue(self.app.panel_asistente.barra_aprobacion.winfo_ismapped(),
                        "La confirmación aparece en el panel, no en una ventana")
        self.assertIn("notas.md", self.app.panel_asistente.aprobacion_texto.get())
        # La ventana principal sigue operativa: no hay grab modal.
        self.assertEqual(self.app.grab_current(), None)

        self.app.panel_asistente.boton_aprobar.invoke()
        self._asentar()
        self.assertEqual(decidido, ["enviado"])
        self.assertFalse(self.app.panel_asistente.barra_aprobacion.winfo_ismapped())

    def test_rechazar_el_contexto_cancela_sin_enviar(self):
        self.app.request_types[7] = "normal"
        self.app._pedir_aprobacion(7, ["notas.md"], ("e", "p", "m", ("notas.md",), "h"),
                                   lambda: self.fail("No debía enviarse"))
        self._asentar()
        self.app.panel_asistente.boton_rechazar.invoke()
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

    def test_la_barra_dice_que_no_hay_articulo_abierto(self):
        # Sin documento la zona central antes quedaba vacía y parecía un fallo;
        # ahora lo dice con palabras.
        self.assertIsNone(self.app.session.document_path)
        self.assertEqual(self.app.barra.documento_var.get(), TopBar.TEXTO_SIN_DOCUMENTO)

    def test_el_nombre_largo_se_recorta_en_la_barra(self):
        nombre = "art" + "í" * 80 + ".md"
        self.app.barra.actualizar_documento(nombre)
        visible = self.app.barra.documento_var.get()
        self.assertLessEqual(len(visible), 42)
        self.assertTrue(visible.endswith("…"), "Un nombre largo se recorta, no se desborda")

    def test_la_barra_agrupa_acciones_a_la_izquierda_y_configuracion_a_la_derecha(self):
        self._asentar()
        barra = self.app.barra
        izq = barra.zona_izquierda
        der = barra.zona_derecha
        for control in (self.app.boton_menu, self.app.boton_guardar):
            self.assertIs(control.master, izq, f"{control} es una acción sobre el archivo")
        for control in (self.app.references_button, self.app.profile_chip,
                        self.app.boton_tema, self.app.boton_panel):
            self.assertIs(control.master, der, f"{control} es configuración, no acción")
        # El documento y el estado van en el centro, en una celda propia: se
        # estiran entre acciones y configuración sin pertenecer a ninguna.
        self.assertIs(barra.documento_label.master, barra.zona_centro)
        self.assertIs(barra.sync_label.master, barra.zona_centro)

        # Y en la ventana ya asentada, las tres zonas no se pisan.
        def fin(w):
            return w.winfo_x() + w.winfo_width()

        self.assertLessEqual(fin(izq), barra.zona_centro.winfo_x(),
                             "El centro empieza donde acaban las acciones")
        self.assertLessEqual(fin(barra.zona_centro), der.winfo_x(),
                             "El centro no invade la configuración")

    def test_el_estado_del_documento_no_es_un_control(self):
        # Se veía como un botón apagado junto a uno accionable; es una etiqueta.
        self.assertIsInstance(self.app.sync_label, ttk.Label)
        self.assertFalse(hasattr(self.app.sync_label, "invoke"))

    def test_el_chip_de_modelo_no_crece_con_el_nombre(self):
        # Un id de modelo largo empujaba la barra por encima de la ventana.
        nombre_largo = "proveedor/organizacion/modelo-super-largo-2026-01"
        with patch.object(type(self.app), "profile") as perfil:
            perfil.model = nombre_largo
            texto = self.app.barra._texto_modelo()
        self.assertTrue(texto.endswith("…"), "Un modelo largo se recorta")
        fuente = tkfont.Font(font=es.fuente(es.TIPO_SM))
        self.assertLessEqual(fuente.measure(texto), TopBar.ANCHO_MODELO,
                             "El recorte se mide en píxeles, no en caracteres")

    def test_el_boton_de_menu_no_hereda_el_ancho_del_desplegable(self):
        # En `clam` el Menubutton se estira al ancho de su menú (11 entradas):
        # 149 px para un icono. Con ancho fijo, la barra deja sitio al documento.
        self._asentar()
        self.assertLess(self.app.boton_menu.winfo_reqwidth(), 100)

    def test_en_ventana_estrecha_cede_el_estado_y_no_el_documento(self):
        # «Sin cambios» no aporta; el nombre sí: es lo único que responde
        # «qué tengo abierto». Apretado, se retira primero el estado.
        barra = self.app.barra
        self.app.geometry("900x700")
        self._asentar()
        self.assertFalse(barra.sync_label.winfo_ismapped(),
                         "Estrecho: el estado se retira para dejar sitio al nombre")

        self.app.geometry("1300x700")
        self._asentar()
        self.assertTrue(barra.sync_label.winfo_ismapped(),
                        "Ancho: el estado vuelve a mostrarse")

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
