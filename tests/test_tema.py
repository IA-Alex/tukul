"""Selector de tema claro/oscuro: paletas, persistencia y reaplicación en vivo.

Cubren los criterios de aceptación del tema:

- el tema oscuro es el predeterminado, también ante valores inválidos y
  estados.json corruptos;
- el tema claro puede activarse, se persiste INMEDIATAMENTE al cambiarlo (sin
  esperar al cierre) y se restaura al reiniciar;
- un fallo de escritura de `estado.json` no rompe ni revierte el cambio visual,
  y el resto del estado persistido se conserva;
- el botón de la barra anuncia la acción correcta según el tema activo;
- widgets, menús y diálogos abiertos se repintan sin perder contenido;
- el zoom sigue funcionando tras el cambio de tema;
- ambas paletas cumplen las reglas de contraste WCAG AA.
"""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_core import storage
from tukul_ui import estilo as es
from tukul_ui.app import TukulApp
from tukul_ui.estado import EstadoUI


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()

#: Tokens que toda paleta debe exponer (la estructura es el contrato).
TOKENS = frozenset({
    "fondo", "superficie", "superficie_alta", "borde", "foco",
    "acento", "acento_activo", "acento_texto", "texto", "texto_tenue",
    "seleccion", "estado_neutro", "estado_proceso", "estado_exito",
    "estado_error", "estado_aviso", "voz_usuario", "voz_asistente",
})


class TestPaletasYTokens(unittest.TestCase):
    """Las paletas son completas, centralizadas y cumplen contraste WCAG AA."""

    def tearDown(self) -> None:
        es.aplicar_tema(es.TEMA_DEFECTO)

    # --- tema predeterminado e inválido ---------------------------------
    def test_el_tema_oscuro_es_el_predeterminado(self):
        self.assertEqual(es.TEMA_ACTIVO, "dark")
        self.assertEqual(es.TEMA_DEFECTO, "dark")
        self.assertEqual(TukulApp._tema_validado(None), "dark")

    def test_el_tema_invalido_vuelve_al_oscuro(self):
        for basura in ("sepia", "", 7, ["dark"], {"theme": "light"}, True, object()):
            self.assertEqual(es.tema_validado(basura), "dark",
                             f"{basura!r} debe caer al tema oscuro")
        self.assertEqual(TukulApp._tema_validado("sepia"), "dark")
        self.assertEqual(TukulApp._tema_validado(["dark"]), "dark")

    # --- activación -----------------------------------------------------
    def test_el_tema_claro_puede_activarse(self):
        es.aplicar_tema("light")
        self.assertEqual(es.TEMA_ACTIVO, "light")
        self.assertEqual(es.FONDO, es.PALETAS["light"]["fondo"])
        self.assertEqual(es.TEXTO, es.PALETAS["light"]["texto"])
        es.aplicar_tema("dark")
        self.assertEqual(es.FONDO, es.PALETAS["dark"]["fondo"])

    def test_ambas_paletas_exponen_los_mismos_tokens(self):
        self.assertEqual(set(es.PALETAS), {"dark", "light"})
        for nombre, paleta in es.PALETAS.items():
            self.assertEqual(set(paleta), TOKENS, f"{nombre} incompleta")

    def test_estados_resuelven_su_color_desde_la_paleta_activa(self):
        es.aplicar_tema("dark")
        oscuro = EstadoUI.EXITO.color
        es.aplicar_tema("light")
        claro = EstadoUI.EXITO.color
        self.assertNotEqual(oscuro, claro)
        self.assertEqual(claro, es.PALETAS["light"]["estado_exito"])
        self.assertEqual(oscuro, es.PALETAS["dark"]["estado_exito"])

    def test_el_tema_vigente_es_la_fuente_unica_de_color(self):
        """`app.COLORS` y `es.colores()` se retiraron: solo queda `PALETAS`."""
        es.aplicar_tema("light")
        self.assertEqual(es.FONDO, es.PALETAS["light"]["fondo"])
        self.assertEqual(es.SUPERFICIE_ALTA, es.PALETAS["light"]["superficie_alta"])
        self.assertEqual(es.ACENTO, es.PALETAS["light"]["acento"])
        self.assertFalse(hasattr(es, "colores"), "el shim muerto no debe volver")
        es.aplicar_tema("dark")

    # --- contraste ------------------------------------------------------
    def test_ambas_paletas_cumplen_contraste_de_texto_normal(self):
        capas = ("fondo", "superficie", "superficie_alta")
        frentes = ("texto", "texto_tenue", "acento", "estado_neutro", "estado_proceso",
                   "estado_exito", "estado_error", "estado_aviso",
                   "voz_usuario", "voz_asistente")
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            for frente in frentes:
                for capa in capas:
                    razon = es.contraste(p[frente], p[capa])
                    self.assertGreaterEqual(
                        razon, 4.5,
                        f"{tema}/{frente} sobre {capa} da {razon:.2f}:1 (WCAG AA pide 4.5)")

    def test_ambas_paletas_cumplen_contraste_de_acento_y_foco(self):
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            for acento in ("acento", "acento_activo"):
                razon = es.contraste(p["acento_texto"], p[acento])
                self.assertGreaterEqual(razon, 4.5,
                                        f"{tema}/acento_texto sobre {acento}: {razon:.2f}")
            for capa in ("fondo", "superficie", "superficie_alta"):
                razon = es.contraste(p["foco"], p[capa])
                self.assertGreaterEqual(razon, 3.0,
                                        f"{tema}/foco contra {capa}: {razon:.2f} (1.4.11 pide 3)")

    def test_ambas_paletas_cumplen_contraste_de_seleccion_y_hover(self):
        for tema in es.PALETAS:
            p = es.PALETAS[tema]
            self.assertGreaterEqual(es.contraste(p["texto"], p["seleccion"]), 4.5,
                                    f"{tema}: texto sobre selección")
            # El hover de los botones usa BORDE como fondo con el texto encima.
            self.assertGreaterEqual(es.contraste(p["texto"], p["borde"]), 4.5,
                                    f"{tema}: texto sobre borde (hover)")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestTemaEnVentanaReal(unittest.TestCase):
    """La ventana montada: botón, widgets, diálogos, persistencia y zoom."""

    def setUp(self):
        self._zoom_previo = es.ZOOM
        es.ZOOM = 1.0
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.config = self.raiz / "config.toml"
        self.documento = self.raiz / "articulo.md"
        self.documento.write_text("# Título\n\nUn párrafo de prueba.\n", encoding="utf-8")
        self.app = TukulApp(self.config)
        self._asentar()

    def tearDown(self):
        es.ZOOM = self._zoom_previo
        es.aplicar_tema(es.TEMA_DEFECTO)
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _toplevels(self, ventana: tk.Misc | None = None) -> list[tk.Toplevel]:
        """Toplevel abiertos bajo la ventana dada (o la principal)."""
        raiz = ventana if ventana is not None else self.app
        return [w for w in raiz.winfo_children() if isinstance(w, tk.Toplevel)]

    def _descendientes(self, ventana: tk.Misc, tipo: type) -> list[tk.Misc]:
        """Widgets del tipo dado bajo `ventana`, en profundidad."""
        resultado: list[tk.Misc] = []
        for hijo in ventana.winfo_children():
            if isinstance(hijo, tipo):
                resultado.append(hijo)
            resultado.extend(self._descendientes(hijo, tipo))
        return resultado

    # --- botón ----------------------------------------------------------
    def test_el_boton_cambia_su_etiqueta_y_tooltip_segun_el_tema(self):
        self.assertEqual(self.app.theme, "dark")
        self.assertIn("Cambiar a claro", self.app.boton_tema.cget("text"))
        self.assertIn("claro", self.app.tooltip_tema.texto)
        self.app._cambiar_tema()
        self._asentar()
        self.assertEqual(self.app.theme, "light")
        self.assertIn("Cambiar a oscuro", self.app.boton_tema.cget("text"))
        self.assertIn("oscuro", self.app.tooltip_tema.texto)
        self.assertIn("claro", self.app.status.get())

    # --- persistencia ---------------------------------------------------
    def test_el_tema_se_persiste_inmediatamente_sin_guardar_estado_ui(self):
        """El botón persiste el tema al instante, sin esperar al cierre."""
        self.app._cambiar_tema()
        self._asentar()
        self.assertEqual(storage.load_ui_state(self.config)["theme"], "light")
        self.app._cambiar_tema()
        self._asentar()
        self.assertEqual(storage.load_ui_state(self.config)["theme"], "dark")

    def test_el_tema_se_restaura_al_crear_una_nueva_instancia(self):
        self.app._cambiar_tema()
        self._asentar()
        self.app.destroy()
        self.app = TukulApp(self.config)
        self._asentar()
        self.assertEqual(self.app.theme, "light")
        self.assertEqual(str(self.app.editor.cget("background")), es.PALETAS["light"]["superficie"])

    def test_un_fallo_de_escritura_no_revierte_el_cambio_visual(self):
        """Si `estado.json` no puede escribirse, la interfaz sigue funcionando."""
        with patch("tukul_core.storage.save_ui_state",
                   side_effect=OSError("disco lleno")):
            self.app._cambiar_tema()
            self._asentar()
        self.assertEqual(self.app.theme, "light")
        self.assertIn("Cambiar a oscuro", self.app.boton_tema.cget("text"))
        self.assertIn("claro", self.app.status.get())
        self.app._cambiar_tema()
        self._asentar()
        self.assertEqual(self.app.theme, "dark")
        # La interfaz sigue operativa: el editor acepta contenido y el zoom vive.
        self.app.editor.insert("end", "\nsobrevive al fallo")
        self.assertIn("sobrevive al fallo", self.app.editor.get("1.0", "end-1c"))

    def test_el_resto_del_estado_persistido_no_se_pierde_al_cambiar_el_tema(self):
        """La escritura inmediata del tema conserva zoom, recientes y conversación."""
        self.app.load_document(self.documento)
        es.ZOOM = 1.2
        self.app._guardar_estado_ui()
        self.app._cambiar_tema()
        self._asentar()
        estado = storage.load_ui_state(self.config)
        self.assertEqual(estado["theme"], "light")
        self.assertEqual(estado["zoom"], 1.2)
        self.assertIn(str(self.documento.resolve()), estado["recent"])

    def test_un_estado_corrupto_no_impide_iniciar(self):
        (self.raiz / "estado.json").write_text("{json roto", encoding="utf-8")
        self.app.destroy()
        self.app = TukulApp(self.config)
        self._asentar()
        self.assertEqual(self.app.theme, "dark")

    def test_un_tema_invalido_persistido_vuelve_al_oscuro(self):
        storage.save_ui_state({"theme": "sepia"}, self.config)
        self.app.destroy()
        self.app = TukulApp(self.config)
        self._asentar()
        self.assertEqual(self.app.theme, "dark")

    # --- widgets y estado -----------------------------------------------
    def test_los_widgets_principales_actualizan_sus_colores(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(self.app.editor.cget("background")), es.PALETAS["light"]["superficie"])
        self.assertEqual(str(self.app.input.cget("background")), es.PALETAS["light"]["superficie_alta"])
        self.assertEqual(str(self.app.history.cget("background")), es.PALETAS["light"]["superficie_alta"])
        self.assertEqual(str(self.app.editor.cget("highlightcolor")), es.PALETAS["light"]["foco"])
        self.assertEqual(str(self.app.editor.cget("insertbackground")), es.PALETAS["light"]["acento"])

    def test_el_estado_de_guardado_se_repinta_sin_perder_simbolo(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.app.editor.insert("end", " editado")
        self._asentar()
        texto = self.app.sync_label.cget("text")
        self.assertTrue(texto.startswith("●"))
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(self.app.sync_label.cget("foreground")), es.PALETAS["light"]["estado_aviso"])
        self.assertEqual(self.app.sync_label.cget("text"), texto, "El estado real no cambia")

    def test_el_estado_de_conversacion_usa_el_color_del_tema(self):
        self.app.set_estado(EstadoUI.ERROR)
        self._asentar()
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(self.app.estado_label.cget("foreground")), es.PALETAS["light"]["estado_error"])
        self.assertEqual(str(self.app.estado_label.cget("foreground")), EstadoUI.ERROR.color)

    # --- contenido conservado -------------------------------------------
    def test_el_editor_y_el_historial_conservan_su_contenido(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.app.append("Tú", "turno conservado")
        self.app.editor.tag_add("sel", "1.0", "1.4")
        self._asentar()
        editor_antes = self.app.editor.get("1.0", "end-1c")
        historial_antes = self.app.history.get("1.0", "end-1c")
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), editor_antes)
        self.assertEqual(self.app.history.get("1.0", "end-1c"), historial_antes)
        self.assertIn("turno conservado", self.app.history.get("1.0", "end-1c"))
        self.assertTrue(self.app.editor.tag_ranges("sel"), "La selección se conserva")

    # --- zoom -----------------------------------------------------------
    def test_el_zoom_sigue_funcionando_despues_de_cambiar_de_tema(self):
        self.app._aplicar_tema("light")
        self._asentar()
        self.app._ajustar_zoom(es.ZOOM_STEP)
        self._asentar()
        self.assertEqual(es.ZOOM, 1.1)
        self.assertIn("110%", self.app.status.get())
        self.app._restablecer_zoom()
        self.assertEqual(es.ZOOM, 1.0)

    # --- menús y diálogos -----------------------------------------------
    def test_los_menus_respetan_el_tema(self):
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(self.app.menu_archivo.cget("background")), es.PALETAS["light"]["superficie_alta"])
        self.assertEqual(str(self.app.menu_recientes.cget("background")), es.PALETAS["light"]["superficie_alta"])

    def test_el_dialogo_de_contexto_respeta_el_tema(self):
        self.app.manage_references()
        self._asentar()
        dialogo = self._toplevels()[-1]
        listas = self._descendientes(dialogo, tk.Listbox)
        self.assertTrue(listas, "El diálogo de contexto debe tener su lista")
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(dialogo.cget("bg")), es.PALETAS["light"]["superficie"])
        self.assertEqual(str(listas[0].cget("background")), es.PALETAS["light"]["superficie_alta"])

    def test_el_dialogo_de_revision_respeta_el_tema(self):
        self.app.show_findings([{
            "category": "gramática", "severity": "alta", "original": "floja",
            "suggestion": "sólida", "reason": "registro coloquial",
        }])
        self._asentar()
        dialogo = self.app.review_dialogs[-1]
        listas = self._descendientes(dialogo, tk.Listbox)
        self.assertTrue(listas)
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(dialogo.cget("bg")), es.PALETAS["light"]["fondo"])
        self.assertEqual(str(listas[0].cget("background")), es.PALETAS["light"]["superficie_alta"])

    def test_el_dialogo_de_configuracion_respeta_el_tema(self):
        self.app.settings()
        self._asentar()
        dialogo = self._toplevels()[-1]
        self.app._aplicar_tema("light")
        self._asentar()
        self.assertEqual(str(dialogo.cget("bg")), es.PALETAS["light"]["fondo"])


if __name__ == "__main__":
    unittest.main()

