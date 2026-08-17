"""Pruebas del estado de interfaz persistente y los ajustes de UX.

Cubren lo añadido en el último tramo: persistencia de geometría/zoom/recientes/
conversación, modo foco, zoom, documentos recientes y métricas de selección.
"""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from articulador_core import storage
from articulador_ui import estilo as es
from articulador_ui.app import ArticuladorApp


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


class TestEstadoPersistente(unittest.TestCase):
    """Persistencia de estado UI: idempotente y aislada por config."""

    def test_estado_ui_vive_junto_al_config(self):
        with tempfile.TemporaryDirectory() as directorio:
            cfg = Path(directorio) / "config.toml"
            self.assertEqual(storage.estado_ui_path(cfg), cfg.with_name("estado.json"))

    def test_estado_ui_roundtrip(self):
        with tempfile.TemporaryDirectory() as directorio:
            cfg = Path(directorio) / "config.toml"
            storage.save_ui_state({"zoom": 1.2, "recent": ["a.md"]}, cfg)
            estado = storage.load_ui_state(cfg)
            self.assertEqual(estado["zoom"], 1.2)
            self.assertEqual(estado["recent"], ["a.md"])

    def test_estado_ui_corrupto_no_falla(self):
        with tempfile.TemporaryDirectory() as directorio:
            cfg = Path(directorio) / "config.toml"
            storage.estado_ui_path(cfg).write_text("{json roto", encoding="utf-8")
            self.assertEqual(storage.load_ui_state(cfg), {})

    def test_estado_ui_inexistente_no_falla(self):
        with tempfile.TemporaryDirectory() as directorio:
            self.assertEqual(storage.load_ui_state(Path(directorio) / "config.toml"), {})


class TestEscalaZoom(unittest.TestCase):
    """El zoom escala la fuente y se valida defensivamente."""

    def tearDown(self):
        es.ZOOM = 1.0

    def test_fuente_escala_con_el_zoom(self):
        es.ZOOM = 1.0
        self.assertEqual(es.fuente(es.TIPO_MD), (es.FAMILIA, es.TIPO_MD))
        es.ZOOM = 1.5
        self.assertEqual(es.fuente(es.TIPO_MD), (es.FAMILIA, round(es.TIPO_MD * 1.5)))

    def test_zoom_validado_acota_y_rechaza_basura(self):
        self.assertEqual(ArticuladorApp._zoom_validado("abc"), 1.0)
        self.assertEqual(ArticuladorApp._zoom_validado(99), es.ZOOM_MAX)
        self.assertEqual(ArticuladorApp._zoom_validado(0), es.ZOOM_MIN)

    def test_recientes_validados_filtra_y_acota(self):
        self.assertEqual(ArticuladorApp._recientes_validados(None), [])
        self.assertEqual(ArticuladorApp._recientes_validados(["a", 3, "", "b"]), ["a", "b"])


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestUxVentanaReal(unittest.TestCase):
    """La ventana montada: foco, zoom, recientes, conversación y métricas."""

    def setUp(self):
        self._zoom_previo = es.ZOOM
        es.ZOOM = 1.0
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.config = self.raiz / "config.toml"
        self.documento = self.raiz / "articulo.md"
        self.documento.write_text("# Título\n\nUn párrafo de prueba.\n", encoding="utf-8")
        self.app = ArticuladorApp(self.config)
        self._asentar()

    def tearDown(self):
        es.ZOOM = self._zoom_previo
        self.app.destroy()
        self.directorio.cleanup()

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    # --- recientes ------------------------------------------------------
    def test_registrar_reciente_actualiza_lista_y_menu(self):
        self.app._registrar_reciente(self.documento)
        self._asentar()
        self.assertEqual(self.app.recent_paths[0], str(self.documento.resolve()))

    def test_reciente_sin_duplicados(self):
        self.app._registrar_reciente(self.documento)
        self.app._registrar_reciente(self.documento)
        self.assertEqual(len(self.app.recent_paths), 1)

    def test_abrir_documento_registra_reciente(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.assertIn(str(self.documento.resolve()), self.app.recent_paths)

    def test_limpiar_recientes_vacia(self):
        self.app._registrar_reciente(self.documento)
        self.app._limpiar_recientes()
        self.assertEqual(self.app.recent_paths, [])

    # --- zoom ----------------------------------------------------------
    def test_zoom_ajusta_el_cuerpo_y_el_estado(self):
        self.app._ajustar_zoom(es.ZOOM_STEP)
        self._asentar()
        self.assertEqual(es.ZOOM, 1.1)
        self.assertIn("110%", self.app.status.get())

    def test_zoom_esta_acotado(self):
        es.ZOOM = es.ZOOM_MAX
        self.app._ajustar_zoom(es.ZOOM_STEP)
        self.assertEqual(es.ZOOM, es.ZOOM_MAX)

    def test_restablecer_zoom_vuelve_a_cien(self):
        es.ZOOM = 1.4
        self.app._restablecer_zoom()
        self.assertEqual(es.ZOOM, 1.0)
        self.assertIn("100%", self.app.status.get())

    # --- modo foco -----------------------------------------------------
    def test_modo_foco_oculta_y_restaura_la_cromada(self):
        self.app.toggle_foco()
        self._asentar()
        self.assertFalse(self.app.barra.winfo_ismapped())
        self.assertFalse(self.app.pie.winfo_ismapped())
        self.app.toggle_foco()
        self._asentar()
        self.assertTrue(self.app.barra.winfo_ismapped())
        self.assertTrue(self.app.pie.winfo_ismapped())

    # --- conversación persistida ---------------------------------------
    def test_restaurar_conversacion_desde_estado(self):
        self.app.ui_state = {"conversations": {
            str(self.documento.resolve()): [
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": "¿en qué te ayudo?"},
            ]
        }}
        self.app.load_document(self.documento)
        self._asentar()
        self.assertEqual(len(self.app.session.conversation), 2)
        self.assertEqual(self.app.session.conversation[0].content, "hola")
        self.assertIn("hola", self.app.history.get("1.0", "end-1c"))

    def test_restaurar_conversacion_descarta_basura(self):
        self.app.ui_state = {"conversations": {
            str(self.documento.resolve()): [{"role": "system", "content": "no válido"}]
        }}
        restaurada = self.app._restaurar_conversacion(self.documento.resolve())
        self.assertEqual(restaurada, [])

    def test_guardar_estado_ui_persiste_zoom_y_recientes(self):
        self.app.load_document(self.documento)
        es.ZOOM = 1.2
        self.app._guardar_estado_ui()
        estado = storage.load_ui_state(self.config)
        self.assertEqual(estado["zoom"], 1.2)
        self.assertIn(str(self.documento.resolve()), estado["recent"])

    def test_conversacion_es_por_documento_no_de_sesion(self):
        """Cambiar de artículo cambia de hebra: cada documento tiene la suya."""
        from articulador_core.models import ChatMessage

        otro = self.raiz / "otro.md"
        otro.write_text("# Otro\n", encoding="utf-8")

        self.app.load_document(self.documento)
        self._asentar()
        self.app.session.conversation.append(ChatMessage("user", "turno del primero"))
        self.app.append("Tú", "turno del primero")

        self.app.load_document(otro)
        self._asentar()
        self.assertEqual(self.app.session.conversation, [])
        self.assertNotIn("turno del primero", self.app.history.get("1.0", "end-1c"))

        self.app.load_document(self.documento)
        self._asentar()
        self.assertEqual(len(self.app.session.conversation), 1)
        self.assertEqual(self.app.session.conversation[0].content, "turno del primero")
        self.assertIn("turno del primero", self.app.history.get("1.0", "end-1c"))

    def test_guardar_estado_ui_poda_conversaciones_fuera_de_recientes(self):
        """estado.json no acumula para siempre conversaciones de documentos ya olvidados."""
        self.app.ui_state = {"conversations": {
            "/ruta/fantasma/no-en-recientes.md": [{"role": "user", "content": "viejo"}],
        }}
        self.app.recent_paths = []
        self.app.load_document(self.documento)
        self.app._guardar_estado_ui()
        estado = storage.load_ui_state(self.config)
        self.assertNotIn("/ruta/fantasma/no-en-recientes.md", estado["conversations"])
        self.assertIn(str(self.documento.resolve()), estado["conversations"])

    # --- métricas de selección -----------------------------------------
    def test_la_seleccion_refleja_su_recuento_en_el_pie(self):
        self.app.load_document(self.documento)
        self._asentar()
        self.app.editor.tag_add("sel", "1.0", "1.6")
        self.app.update_stats()
        self._asentar()
        self.assertIn(" de ", self.app.editor_stats.cget("text"))


if __name__ == "__main__":
    unittest.main()
