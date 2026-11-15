"""Regresión de los defectos visuales medidos en la ventana real.

Cada prueba fija un comportamiento que se rompió en la práctica y que una
captura de pantalla delató:

- el nombre del artículo caía a 3 px cuando la barra se estrechaba;
- la guía del asistente se cortaba a media palabra (wraplength fijo);
- «Cancelar» se partía («Cance») durante una consulta;
- el panel del asistente pedía 1123 px por el ancho en caracteres de sus
  áreas de texto, así que su columna derecha se recortaba;
- el divisor era un tubo de 10 px con marcas de agarre.

Las pruebas puras (sin ventana) se ejecutan siempre; las que miden widgets
reales se saltan sin servidor X, igual que el resto de la suite.

**Regresión vs. invariante.** Cada prueba de este módulo se comprobó en las dos
direcciones: las de *regresión* fallan sobre el código anterior a la corrección
y pasan después; las de *invariante* ya pasaban antes y lo que fijan es que la
corrección no rompa algo que debía seguir siendo cierto. Se marcan como
invariante en su propia docstring: declararlas regresión daría por probado un
rojo/verde que no existe, y en un fallo futuro no se sabría si algo se rompió
o si la prueba nació verde.
"""
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_ui import estilo as es
from tukul_ui.app import TukulApp
from tukul_ui.components.top_bar import TopBar
from tukul_ui.estado import EstadoUI


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


class TestRepartoDeLaBarra(unittest.TestCase):
    """Qué piezas de la barra ceden con cada ancho (lógica pura)."""

    def _desplazamiento(self, ancho: int) -> dict[str, bool]:
        # Lógica pura de clase: no depende de estado de instancia.
        return TopBar._desplazamiento_por_ancho(ancho)

    def test_la_ventana_minima_retira_el_estado_y_los_controles_secundarios(self):
        """A 1120 px el nombre del artículo se quedaba en 3 px.

        Medicion: los tres controles de configuración (Contexto, Modelo, Tema)
        conservaban su ancho completo y el centro cedía hasta desaparecer. En
        la ventana mínima deben retirarse los secundarios y el estado; el
        nombre nunca.
        """
        desplazamiento = self._desplazamiento(es_ancho_minimo())
        self.assertFalse(desplazamiento["secundarios"],
                         "En la ventana mínima sobran los controles de configuración")
        self.assertFalse(desplazamiento["estado"],
                         "El estado también cede en la ventana mínima")

    def test_una_barra_holgada_muestra_todo(self):
        desplazamiento = self._desplazamiento(1600)
        self.assertTrue(desplazamiento["estado"])
        self.assertTrue(desplazamiento["secundarios"])

    def test_el_estado_se_retira_antes_que_los_controles(self):
        """Orden de cesión: primero el estado, después la configuración."""
        entrelazado = self._desplazamiento(1100)
        self.assertFalse(entrelazado["estado"])
        self.assertFalse(entrelazado["secundarios"])
        holgado = self._desplazamiento(TopBar.ANCHO_SECUNDARIOS)
        self.assertTrue(holgado["secundarios"])


def es_ancho_minimo() -> int:
    from tukul_ui.app import ANCHO_MINIMO_VENTANA

    return ANCHO_MINIMO_VENTANA


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestVentanaSinDesbordes(unittest.TestCase):
    """Medidas sobre la ventana montada: nada se sale de su contenedor."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.app = TukulApp(self.raiz / "config.toml")
        self.app.geometry("1180x760+0+0")
        self._asentar()

    def tearDown(self):
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_el_panel_del_asistente_no_pide_mas_ancho_que_la_ventana(self):
        """Regresión: sus áreas de texto heredaban un ancho de 80 caracteres.

        Con eso, el panel pedía 1123 px en la ventana de 1180, `pack` repartía
        por encima y la columna derecha (donde vive «Cancelar») se recortaba.
        """
        panel = self.app.panel_asistente
        self.assertLessEqual(panel.winfo_reqwidth(), self.app.winfo_width(),
                             "El panel no debe pedir más ancho que la ventana")
        self.assertLessEqual(panel.history.winfo_reqwidth(), panel.winfo_width(),
                             "El historial debe caber dentro del panel")

    def test_cancelar_conserva_su_texto_entero_durante_una_consulta(self):
        """Regresión: con una petición viva se veía «Cance»."""
        boton = self.app.panel_asistente.cancel_button
        self.app.set_estado(EstadoUI.TRANSMITIENDO, "revisando artículo")
        self._asentar()
        self.assertTrue(boton.winfo_ismapped(), "Cancelar debe mostrarse")
        self.assertEqual(boton.cget("text"), "Cancelar")
        self.assertGreaterEqual(boton.winfo_width(), boton.winfo_reqwidth(),
                                "Cancelar recibe menos ancho del que pide su texto")
        fila = self.app.panel_asistente.fila_acciones
        borde = boton.winfo_x() + boton.winfo_width()
        self.assertLessEqual(borde, fila.winfo_width(),
                             "Cancelar se sale de la fila de acciones")

    def test_al_terminal_la_consulta_la_fila_vuelve_a_su_estado_de_reposo(self):
        """Invariante (no regresión): ya pasaba antes de la corrección.

        Fija que el reparto por columnas de «Cancelar» conserve la condición de
        reposo que ya cumplía el `pack` anterior; su valor es impedir que la
        corrección del truncado reintroduzca una columna vacía al terminar.
        """
        panel = self.app.panel_asistente
        self.app.set_estado(EstadoUI.TRANSMITIENDO, "revisando")
        self._asentar()
        self.app.set_estado(EstadoUI.EXITO)
        self._asentar()
        self.assertFalse(panel.cancel_button.winfo_ismapped(),
                         "Sin consulta viva no debe quedar la columna de Cancelar")

    def test_la_guia_del_panel_ajusta_su_salto_al_ancho_real(self):
        """Regresión: con 520 px fijos se leía «…su estruc»."""
        panel = self.app.panel_asistente
        self._asentar()
        salto = int(float(panel.guia_label.cget("wraplength")))
        self.assertGreater(salto, 0, "La guía debe tener un ancho de salto útil")
        self.assertLessEqual(salto, panel.winfo_width(),
                             "El salto de la guía no puede exceder el panel")

    def test_los_textos_del_panel_usan_la_superficie_en_que_viven(self):
        """El aviso de uso vive sobre la superficie elevada del compositor."""
        estilo = str(self.app.panel_asistente.cost_label.cget("style"))
        self.assertEqual(estilo, "TenueSuperficieAlta.TLabel")

    def test_el_isotipo_de_la_cabecera_mide_18_px(self):
        """Criterio F4 del contrato: el isotipo de cabecera baja a 18 px.

        El contrato lo compromete con un valor concreto, pero la suite no lo
        comprobaba: subirlo a 24 px (donde el dibujo se leía como un borrón y
        robaba ancho al nombre) pasaba en verde. Se fija aquí para que la
        promesa de 18 px tenga una regresión que la sostenga.
        """
        barra = self.app.barra
        self.assertEqual(TopBar.LOGO, 18, "El isotipo de cabecera promete 18 px")
        self._asentar()
        self.assertEqual(int(barra.logo.cget("width")), TopBar.LOGO,
                         "El canvas del isotipo no mide lo que declara LOGO")
        self.assertEqual(int(barra.logo.cget("height")), TopBar.LOGO)
        self.assertEqual(barra.logo.winfo_width(), TopBar.LOGO,
                         "El isotipo montado no ocupa los 18 px comprometidos")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestDivisorDiscreto(unittest.TestCase):
    """El sash separa sin parecer un panel de app antigua."""

    def test_el_divisor_es_un_carril_fino_sin_marcas(self):
        from tkinter import ttk

        raiz = tk.Tk()
        self.addCleanup(raiz.destroy)
        from tukul_ui import tema

        tema.aplicar_estilos(raiz, "dark", lambda: None)
        estilo = ttk.Style(raiz)
        self.assertLessEqual(int(estilo.lookup("Sash", "sashthickness")), 2,
                             "El divisor grueso roba ancho al artículo")
        self.assertEqual(str(estilo.lookup("Sash", "gripcount")), "0")

    def test_el_divisor_sigue_siendo_perceptible_y_accesible(self):
        """Invariante (no regresión): ya pasaba antes de la corrección.

        WCAG 1.4.11: el sash se arrastra, así que mantiene 3:1 sobre el fondo.
        El adelgazado de 10 px a 1 px es justo el cambio que podía romper esta
        condición de contraste, que ya se cumplía; de ahí que se vigile.
        """
        for tema, paleta in es.PALETAS.items():
            self.assertGreaterEqual(es.contraste(paleta["borde_control"], paleta["fondo"]),
                                    3.0, f"El divisor de {tema} deja de ser visible")


if __name__ == "__main__":
    unittest.main()
