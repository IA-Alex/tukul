"""Pruebas del estado de interfaz persistente y los ajustes de UX.

Cubren lo añadido en el último tramo: persistencia de geometría/zoom/recientes/
conversación, modo foco, zoom, documentos recientes y métricas de selección.
"""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_core import storage
from tukul_ui import estilo as es
from tukul_ui.app import TukulApp


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

    def test_estado_ui_demasiado_grande_no_se_carga(self):
        with tempfile.TemporaryDirectory() as directorio:
            cfg = Path(directorio) / "config.toml"
            estado = storage.estado_ui_path(cfg)
            estado.write_bytes(b" " * (storage.MAX_UI_STATE_BYTES + 1))
            self.assertEqual(storage.load_ui_state(cfg), {})

    def test_estado_ui_demasiado_grande_no_se_guarda(self):
        with tempfile.TemporaryDirectory() as directorio:
            cfg = Path(directorio) / "config.toml"
            with self.assertRaises(ValueError):
                storage.save_ui_state({"contenido": "x" * storage.MAX_UI_STATE_BYTES}, cfg)


class TestEscalaZoom(unittest.TestCase):
    """El zoom escala la fuente y se valida defensivamente.

    La familia NO se fija aquí: la resuelve `_aplicar_dpi` al construir la
    ventana con las fuentes realmente instaladas. En un runner de CI no hay
    «Inter» y la familia activa es, por ejemplo, «DejaVu Sans». Asumir
    `es.FAMILIA` hacía fallar la suite en CI pero no en un escritorio con
    «Inter», que es justo la diferencia que este test debe respetar.
    """

    def tearDown(self):
        es.ZOOM = 1.0

    def test_fuente_escala_con_el_zoom(self):
        es.ZOOM = 1.0
        familia, cuerpo, *_ = es.fuente(es.TIPO_MD)
        self.assertEqual(familia, es._familia_activa or es.FAMILIA)
        self.assertEqual(cuerpo, round(es.TIPO_MD * 1.0))

        es.ZOOM = 1.5
        familia_zoom, cuerpo_zoom, *_ = es.fuente(es.TIPO_MD)
        self.assertEqual(familia_zoom, familia)
        self.assertEqual(cuerpo_zoom, round(es.TIPO_MD * 1.5))

    def test_fuente_usa_la_familia_resuelta_por_la_ventana(self):
        """Regresión: con una familia instalada, `fuente()` la usa tal cual."""
        es.ZOOM = 1.0
        anteriores = es._familia_activa
        try:
            es.resolver_familia(["DejaVu Sans", "Liberation Sans"])
            self.assertEqual(es.fuente(es.TIPO_MD)[0], "DejaVu Sans")
        finally:
            es._familia_activa = anteriores

    def test_zoom_validado_acota_y_rechaza_basura(self):
        self.assertEqual(TukulApp._zoom_validado("abc"), 1.0)
        self.assertEqual(TukulApp._zoom_validado(99), es.ZOOM_MAX)
        self.assertEqual(TukulApp._zoom_validado(0), es.ZOOM_MIN)

    def test_recientes_validados_filtra_y_acota(self):
        self.assertEqual(TukulApp._recientes_validados(None), [])
        self.assertEqual(TukulApp._recientes_validados(["a", 3, "", "b"]), ["a", "b"])


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
        self.app = TukulApp(self.config)
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

    # --- geometría -----------------------------------------------------
    def test_geometria_con_posicion_negativa_se_restaura_en_tk(self):
        """Tk escribe «+-61»; esa geometría debe volver a aplicarse sin error.

        La ventana guardada a la izquierda o por encima del origen del
        escritorio se abría con el tamaño por defecto porque la lectura
        descartaba la cadena. Se comprueba contra Tk real: el formato se acepta
        y la ventana termina dentro del escritorio.
        """
        pantalla_ancho = self.app.winfo_screenwidth()
        pantalla_alto = self.app.winfo_screenheight()
        saneada = TukulApp._geometria_saneada("1920x1011+-61+-23", pantalla_ancho, pantalla_alto)
        self.assertIsNotNone(saneada)
        self.assertNotIn("+-", saneada)
        self.app.geometry(saneada)
        for _ in range(5):
            self.app.update()
        self.app.update_idletasks()
        ancho, alto, x, y = map(int, TukulApp.PATRON_GEOMETRIA.fullmatch(
            self.app.geometry()).groups())
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + ancho, pantalla_ancho)
        self.assertLessEqual(y + alto, pantalla_alto)

    def test_guardado_normaliza_la_geometria_persistida(self):
        """Lo escrito en estado.json se reabre en la próxima sesión tal cual."""
        self.app.geometry("1100x700+-40+-30")
        self._asentar()
        estado = self.app._snapshot_estado_ui()
        self.assertNotIn("+-", estado["geometry"])
        self.assertIsNotNone(TukulApp.PATRON_GEOMETRIA.fullmatch(estado["geometry"]))
        self.app._guardar_estado_ui()
        self.assertEqual(storage.load_ui_state(self.config)["geometry"], estado["geometry"])

    def test_cerrar_sin_mapear_no_pisa_la_geometria_guardada(self):
        """Sin ventana mapeada `geometry()` devuelve «1x1+0+0».

        Guardarlo convertía la próxima apertura en una miniatura de 1120x540.
        Cuando no hay medida real, se conserva la última geometría de disco.
        """
        storage.save_ui_state({"geometry": "1180x760+10+10"}, self.config)
        self.app.ui_state = storage.load_ui_state(self.config)
        with patch.object(TukulApp, "_ventana_mapeada", return_value=False):
            estado = self.app._snapshot_estado_ui()
        self.assertEqual(estado["geometry"], "1180x760+10+10")

        with patch.object(TukulApp, "_ventana_mapeada", return_value=True), \
                patch.object(TukulApp, "geometry", return_value="1x1+0+0"):
            estado = self.app._snapshot_estado_ui()
        self.assertEqual(estado["geometry"], "1120x540+0+0",
                         "Mapeada sí se sanea, aunque el valor sea mínimo")

    def test_geometria_invalida_abre_con_tamano_por_defecto(self):
        """Basura persistida no rompe el arranque: se ignora y se usa el tamaño acorde."""
        self.assertIsNone(TukulApp._geometria_saneada("1920x1011+-6x1+-23", 1920, 1080))
        self.assertIsNone(TukulApp._geometria_saneada(None, 1920, 1080))
        self.assertIsNone(TukulApp._geometria_saneada("1180x760+0+0", 0, 0))

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
        from tukul_core.models import ChatMessage

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
