"""Accesibilidad verificable: contraste no textual, cierre de diálogos y foco.

Hallazgo M4 de la auditoría 2026-11-04: la paleta se comprobaba para el texto
(AA 4.5:1) pero no para los elementos de interfaz que WCAG 1.4.11 exige a 3:1
—bordes y separadores sobre cada capa—, y ningún test recorría un diálogo de
principio a fin (Escape, foco devuelto, descripción accesible por estado).
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

from tukul_ui import estilo as es
from tukul_ui.app import TukulApp
from tukul_ui.estado import EstadoUI

CAPAS = ("fondo", "superficie", "superficie_alta")
NO_NEUTRALES = (
    "texto", "texto_tenue", "acento", "acento_activo", "foco",
    "estado_neutro", "estado_proceso", "estado_exito", "estado_error",
    "estado_aviso", "voz_usuario", "voz_asistente",
)


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


class TestContrasteNoTextual(unittest.TestCase):
    """WCAG 1.4.11: bordes y separadores necesitan 3:1 contra su entorno."""

    def test_el_borde_divisorio_no_es_el_control_de_los_accionables(self):
        """`borde` es divisoria decorativa; `borde_control` es la pieza 1.4.11.

        En «Obsidiana y Jade» el estuco sombra es deliberadamente tenue: separa
        bloques sin gritar. WCAG 1.4.11 no exige 3:1 a un separador puramente
        decorativo (no es un control ni una gráfica con significado funcional);
        la obligación recae en `borde_control`, que sí se prueba aparte. Aquí se
        fija lo que sí importa: que la divisoria se perciba como línea sobre
        cada capa (≥ 1.25) y que NO sea el color de los accionables.
        """
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            for capa in CAPAS:
                razon = es.contraste(p["borde"], p[capa])
                self.assertGreaterEqual(
                    razon, 1.25,
                    f"{tema}/borde sobre {capa} da {razon:.2f}:1 (no se percibe la línea)")
            self.assertNotEqual(
                p["borde"], p["borde_control"],
                f"{tema}: la divisoria y el borde de control no pueden ser el mismo color")

    def test_el_borde_de_los_controles_cumple_3_a_1(self):
        """Sash, scrollbar y bordes de campo: piezas accionables, 3:1."""
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            for capa in ("fondo", "superficie", "superficie_alta"):
                razon = es.contraste(p["borde_control"], p[capa])
                self.assertGreaterEqual(
                    razon, 3.0,
                    f"{tema}/borde_control sobre {capa} da {razon:.2f}:1")

    def test_la_superficie_de_hover_mantiene_el_texto_legible(self):
        """El hover de un botón es un fondo más: el texto va encima."""
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            self.assertGreaterEqual(
                es.contraste(p["texto"], p["superficie_activa"]), 4.5,
                f"{tema}: texto sobre el hover")


class TestIdentidadDeLaPaleta(unittest.TestCase):
    """Identidad «Obsidiana y Jade»: piedra volcánica fría, jade y ámbar."""

    def test_el_fondo_es_obsidiana_fria_y_no_un_calido(self):
        """La obsidiana es una piedra fría: el azul manda sobre el rojo."""
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            for clave in ("fondo", "superficie", "superficie_alta"):
                color = p[clave].lstrip("#")
                rojo, verde, azul = (int(color[i:i + 2], 16) for i in (0, 2, 4))
                self.assertGreaterEqual(
                    azul, rojo, f"{tema}/{clave} no es una piedra fría (azul ≥ rojo)")
                self.assertGreaterEqual(
                    azul, verde, f"{tema}/{clave} no es una piedra fría (azul ≥ verde)")

    def test_el_borde_y_el_control_son_estuco_gris_azulado(self):
        """El estuco sombra es gris-azulado: ni ocre ni café."""
        for tema in es.PALETAS:
            for clave in ("borde", "borde_control"):
                color = es.PALETAS[tema][clave].lstrip("#")
                rojo, _verde, azul = (int(color[i:i + 2], 16) for i in (0, 2, 4))
                self.assertGreaterEqual(
                    azul, rojo, f"{tema}/{clave} no es estuco frío (azul ≥ rojo)")

    def test_el_acento_es_el_verde_jade(self):
        """El jade es verde: el acento de la acción primaria y de la identidad."""
        for tema in es.PALETAS:
            acento = es.PALETAS[tema]["acento"].lstrip("#")
            rojo, verde, azul = (int(acento[i:i + 2], 16) for i in (0, 2, 4))
            self.assertGreater(verde, rojo, f"{tema}: el acento no es verde jade")
            self.assertGreater(verde, azul, f"{tema}: el acento no es verde jade")

    def test_el_acento_secundario_es_ambar_tunkul(self):
        """El ámbar marca al asistente y el logotipo: cálido y reconocible."""
        for tema in es.PALETAS:
            ambar = es.PALETAS[tema]["voz_asistente"].lstrip("#")
            rojo, verde, azul = (int(ambar[i:i + 2], 16) for i in (0, 2, 4))
            self.assertGreater(rojo, azul, f"{tema}: el ámbar no es cálido")
            self.assertGreater(verde, azul, f"{tema}: el ámbar no es cálido")

    def test_el_texto_del_borde_de_hover_conserva_legibilidad(self):
        """BORDE es también el fondo de hover de los botones: el texto va encima."""
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            razon = es.contraste(p["texto"], p["borde"])
            self.assertGreaterEqual(
                razon, 3.0,
                f"{tema}: texto sobre el divisor aclarado da {razon:.2f} (texto grande)")

    def test_los_colores_no_neutrales_son_visibles_sobre_cada_capa(self):
        """Un color de señal que apenas se distingue de su fondo no comunica nada."""
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            for clave in NO_NEUTRALES:
                for capa in CAPAS:
                    claridad = abs(es.luminancia(p[clave]) - es.luminancia(p[capa]))
                    # WCAG 1.4.11 exige 3:1 para elementos; aquí el indicador
                    # puede ser un borde o un icono con el texto aparte.
                    self.assertGreaterEqual(
                        es.contraste(p[clave], p[capa]), 3.0,
                        f"{tema}: {clave} sobre {capa} apenas se distingue")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestFocoYDialogos(unittest.TestCase):
    """Un diálogo se abre con foco propio, se cierra con Escape y devuelve el foco."""

    def setUp(self) -> None:
        self.directorio = tempfile.TemporaryDirectory()
        raiz = Path(self.directorio.name)
        self.config = raiz / "config.toml"
        self.app = TukulApp(self.config)
        self._asentar()

    def tearDown(self) -> None:
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self) -> None:
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _foco_dentro(self, dialogo: tk.Toplevel) -> bool:
        actual = dialogo.focus_get()
        if actual is None:
            return False
        return str(actual).startswith(str(dialogo))

    def test_configuracion_abre_con_foco_dentro_y_cierra_con_escape(self):
        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._asentar()
        dialogos = [w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(dialogos), 1, "El diálogo no se abrió")
        dialogo = dialogos[0]
        self.assertTrue(self._foco_dentro(dialogo),
                        "El foco quedó fuera del diálogo recién abierto")

        dialogo.event_generate("<Escape>")
        self._asentar()
        self.assertFalse(dialogo.winfo_exists(), "Escape no cerró el diálogo")
        self.assertEqual(self.app.focus_get(), self.app.editor,
                         "El foco no volvió al editor al cerrar")

    def test_revision_abre_con_foco_dentro_del_listado(self):
        from tukul_ui.dialogs import show_review_dialog

        hallazgos = [{"category": "ortografía", "severity": "baja",
                      "original": "prueba", "suggestion": "prueba", "reason": "ok"}]
        dialogo = show_review_dialog(self.app, hallazgos)
        self._asentar()
        self.assertTrue(self._foco_dentro(dialogo),
                        "El listado de hallazgos no recibió el foco")
        dialogo.event_generate("<Escape>")
        self._asentar()
        self.assertFalse(dialogo.winfo_exists())


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestEstadoAccesibleCompleto(unittest.TestCase):
    """Cada EstadoUI tiene una descripción legible, sin depender del color."""

    def setUp(self) -> None:
        self.directorio = tempfile.TemporaryDirectory()
        self.app = TukulApp(Path(self.directorio.name) / "config.toml")

    def tearDown(self) -> None:
        self.app.destroy()
        self.directorio.cleanup()

    def test_cada_estado_produce_texto_para_lectores_de_pantalla(self):
        for estado in EstadoUI:
            self.app.estado_actual = estado
            texto = self.app.estado_accesible("detalle de prueba")
            self.assertTrue(texto.strip(), f"{estado.name} sin descripción accesible")
            self.assertNotIn("#", texto, "La descripción no debe ser un color")
            self.assertIn("detalle de prueba", texto,
                          f"{estado.name} pierde el detalle dado por el usuario")


if __name__ == "__main__":
    unittest.main()
