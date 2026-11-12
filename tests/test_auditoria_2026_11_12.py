"""Regresiones de la auditoría desktop + diseño 2026-11-12.

Cubren los defectos confirmados allí:

- DF-001: el zoom no repintaba la línea de estado, la barra de aprobación ni los
  menús (fuentes explícitas fuera de `ttk.Style`).
- DF-002: `ScrolledText` usa `Scrollbar` y `Frame` clásicos de Tk, que ignoran
  los estilos `*.TScrollbar`; quedaban claros dentro de los temas.
- DF-003: el listado de hallazgos del diálogo de revisión no tenía scrollbar.
- DF-004: la lista de ideas comunicaba urgencia/audiencia solo con emoji.
- DF-005: los subtítulos de narración de los paneles.
- DF-006: el nombre del documento se recortaba por caracteres, no por píxeles.
"""
from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from tukul_ui import estilo as es
from tukul_ui.app import TukulApp
from tukul_ui.components.top_bar import TopBar


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class BaseConApp(unittest.TestCase):
    """App real mínima, con config aislado por prueba."""

    def setUp(self) -> None:
        self.directorio = tempfile.TemporaryDirectory()
        self.app = TukulApp(Path(self.directorio.name) / "config.toml")
        self._asentar()

    def tearDown(self) -> None:
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self) -> None:
        for _ in range(4):
            self.app.update()
            self.app.update_idletasks()


class TestZoomCoherente(BaseConApp):
    """DF-001: al cambiar el zoom, todo portador con fuente explícita escala."""

    def _tamano(self, widget) -> int:
        fuente = str(widget.cget("font")).split()
        return int(fuente[1]) if len(fuente) > 1 else int(widget.cget("font"))

    def test_la_linea_de_estado_crece_con_el_zoom(self):
        antes = self._tamano(self.app.estado_label)
        es.ZOOM = 1.4
        self.addCleanup(setattr, es, "ZOOM", 1.0)
        self.app._aplicar_escala()
        self.assertGreater(self._tamano(self.app.estado_label), antes,
                           "La línea de estado no siguió el zoom")

    def test_los_menus_de_la_barra_crecen_con_el_zoom(self):
        antes = self._tamano(self.app.menu_archivo)
        es.ZOOM = 1.4
        self.addCleanup(setattr, es, "ZOOM", 1.0)
        self.app._aplicar_escala()
        self.assertGreater(self._tamano(self.app.menu_archivo), antes,
                           "El menú de la barra no siguió el zoom")

    def test_el_editor_sigue_siendo_el_mayor(self):
        # La jerarquía se conserva: la prosa no puede quedar más pequeña que los
        # controles tras escalar.
        es.ZOOM = 1.3
        self.addCleanup(setattr, es, "ZOOM", 1.0)
        self.app._aplicar_escala()
        self.assertGreater(self._tamano(self.app.editor),
                           self._tamano(self.app.estado_label))


class TestScrollClasicoTematico(BaseConApp):
    """DF-002: las áreas `ScrolledText` visten su barra y su marco con el tema."""

    def _colores(self, area):
        return area.vbar.cget("background"), area.frame.cget("background")

    def test_la_barra_del_editor_no_es_el_gris_por_defecto(self):
        barra, _ = self._colores(self.app.editor)
        self.assertNotEqual(barra.lower(), "#d9d9d9",
                            "La barra del editor quedó con el gris por defecto de Tk")

    def test_el_marco_del_historial_sigue_la_superficie(self):
        _, marco = self._colores(self.app.history)
        self.assertEqual(marco, es.SUPERFICIE_ALTA,
                         "El marco del historial no sigue la superficie del tema")

    def test_la_barra_se_repinta_al_cambiar_de_tema(self):
        self.app._aplicar_tema("light")
        self._asentar()
        barra, marco = self._colores(self.app.input)
        self.assertNotEqual(barra.lower(), "#d9d9d9")
        self.assertEqual(marco, es.SUPERFICIE_ALTA)


class TestHallazgosConScroll(BaseConApp):
    """DF-003: el listado de la revisión es navegable con el ratón."""

    def test_el_listbox_de_revision_tiene_scrollbar(self):
        from tukul_ui.dialogs import show_review_dialog

        hallazgos = [{"category": "ortografía", "severity": "baja",
                      "original": f"frag{i}", "suggestion": "x",
                      "reason": "ok"} for i in range(30)]
        dialogo = show_review_dialog(self.app, hallazgos)
        self._asentar()
        envuelto = _buscar_listbox_con_scroll(dialogo)
        self.assertTrue(envuelto,
                        "El listado de hallazgos no tiene barra de desplazamiento")


class TestIdeasEtiquetadas(BaseConApp):
    """DF-004: urgencia y audiencia viajan en texto, no solo en el emoji."""

    def test_la_fila_de_idea_escribe_urgencia_y_audiencia(self):
        from types import SimpleNamespace

        from tukul_ui.ideas import IdeasController

        ideas = [SimpleNamespace(
            title="Una idea", angle="a", reasoning="r",
            target_audience="directivos", urgency="inmediata",
            confidence=0.9, correlation_id="c1",
        )]
        correlaciones = [SimpleNamespace(id="c1", sources=["fuente"])]
        antes = set(self.app.winfo_children())
        controller = IdeasController(self.app, Path(self.directorio.name), 24)
        controller.show_selection_dialog(self.app, ideas, [], correlaciones, lambda: None)
        self._asentar()
        dialogos = [w for w in self.app.winfo_children()
                    if isinstance(w, tk.Toplevel) and w not in antes]
        self.assertTrue(dialogos, "No se abrió el diálogo de ideas")
        dialogo = dialogos[0]
        listbox = _buscar_widget(dialogo, tk.Listbox)
        self.assertIsNotNone(listbox, "No se encontró la lista de ideas")
        fila = listbox.get(0)
        self.assertIn("inmediata", fila, "La urgencia no está escrita en la fila")
        self.assertIn("directivos", fila, "La audiencia no está escrita en la fila")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestNombreDocumentoPorPixeles(unittest.TestCase):
    """DF-006: el recorte del nombre se mide en píxeles."""

    def test_un_nombre_largo_se_recorta_y_cabe(self):
        import tkinter.font as tkfont

        raiz = tk.Tk()
        self.addCleanup(raiz.destroy)
        barra = TopBar.__new__(TopBar)
        barra.documento_label = tk.Label(raiz)
        nombre = "un-articulo-con-un-nombre-extraordinariamente-largo-2026.md"
        visible = barra._nombre_recortado(nombre)
        self.assertTrue(visible.endswith("…"), "Un nombre largo se recorta")
        fuente = tkfont.Font(font=es.fuente(es.TIPO_SM))
        self.assertLessEqual(fuente.measure(visible), TopBar.ANCHO_DOCUMENTO)

    def test_un_nombre_corto_no_se_toca(self):
        raiz = tk.Tk()
        self.addCleanup(raiz.destroy)
        barra = TopBar.__new__(TopBar)
        barra.documento_label = tk.Label(raiz)
        self.assertEqual(barra._nombre_recortado("nota.md"), "nota.md")


def _buscar_widget(raiz, tipo):
    """Primer descendiente del tipo pedido, en anchura."""
    for hijo in raiz.winfo_children():
        if isinstance(hijo, tipo):
            return hijo
        encontrado = _buscar_widget(hijo, tipo)
        if encontrado is not None:
            return encontrado
    return None


def _buscar_listbox_con_scroll(raiz) -> bool:
    """¿Hay un Listbox acompañado de un `ttk.Scrollbar` en el mismo contenedor?"""
    from tkinter import ttk

    listbox = _buscar_widget(raiz, tk.Listbox)
    if listbox is None:
        return False
    contenedor = listbox.master
    return any(isinstance(w, ttk.Scrollbar) for w in contenedor.winfo_children())


if __name__ == "__main__":
    unittest.main()
