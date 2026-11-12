"""Regresiones de la auditoría estructural — petición y UI.

Dividido de `test_auditoria_regresion.py` (1.544 líneas, 22 clases mezclando
dominios) por dominio. Cada prueba ejecuta código de producción: si se revierte
la corrección, la prueba falla.
"""
import io
import os
import queue
import stat
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from _regresion_helpers import (
    HAS_DISPLAY,
    _display_available,
    _esperar_hilo_de_envio,
    _headless_app,
)

from tukul_core import storage
from tukul_core.llm import LLMClient, LlmError, validate_endpoint
from tukul_core.models import ArticleSession, LlmProfile
from tukul_ui.app import TukulApp
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import EstadoUI


class TestBombeoDeEventosResiliente(unittest.TestCase):
    """El pump nunca debe morir: si no se reprograma, la app queda sorda."""

    def test_pump_se_reprograma_aunque_falle_un_manejador(self):
        app = _headless_app()
        app.request_types[1] = "normal"
        # usage=None revienta finish() al formatear el uso real.
        app.control_queue.put_nowait(("complete", 1, "ok", [], None, "normal"))

        app.process_ui_events()

        self.assertTrue(app.after.called, "El bombeo debe reprogramarse pese al fallo")
        self.assertEqual(app.after.call_args[0][1], app.process_ui_events)

    def test_un_evento_roto_no_impide_procesar_los_siguientes(self):
        app = _headless_app()
        app.request_types[1] = "normal"
        app.request_types[2] = "normal"
        app.control_queue.put_nowait(("complete", 1, "ok", [], None, "normal"))
        app.chunks.append(2, "hola")

        app.process_ui_events()

        self.assertEqual(app.control_queue.qsize(), 0, "La cola de control debe quedar drenada")
        app.stream_chunk.assert_called_with(2, "hola")

    def test_fallo_de_manejador_libera_la_peticion(self):
        app = _headless_app()
        app.request_types[1] = "normal"
        app.docs.session.request_active = True
        app.control_queue.put_nowait(("complete", 1, "ok", [], None, "normal"))

        app.process_ui_events()

        self.assertNotIn(1, app.request_types)
        app.send_button.state.assert_any_call(["!disabled"])
        app.cancel_button.state.assert_any_call(["disabled"])

class TestSalidaParcialEnError(unittest.TestCase):
    """Un error tras N chunks no debe dejar el mensaje cortado sin explicación."""

    def test_error_tras_streaming_conserva_lo_recibido(self):
        app = _headless_app()
        app.request_types[7] = "normal"
        app.streaming_request = 7
        app.streaming_text = "respuesta a medias"
        app._append_notice = Mock()

        app.finish(7, "No pude responder: timeout", [], (None, None), "normal", is_error=True)

        self.assertEqual(app.scope.last_response, "respuesta a medias")
        self.assertEqual(
            [m.content for m in app.docs.session.conversation], ["respuesta a medias"]
        )
        app._append_notice.assert_called_once()
        self.assertIn("[INCOMPLETO]", app._append_notice.call_args[0][0])

    def test_error_sin_streaming_muestra_el_mensaje_de_error(self):
        app = _headless_app()
        app.request_types[8] = "normal"
        app.append = Mock()

        app.finish(8, "No pude responder: timeout", [], (None, None), "normal", is_error=True)

        app.append.assert_called_once_with("Tukul", "No pude responder: timeout")
        self.assertEqual(list(app.docs.session.conversation), [])

    def test_exito_guarda_el_resultado_completo(self):
        app = _headless_app()
        app.request_types[9] = "normal"
        app.streaming_request = 9
        app.streaming_text = "hola"

        app.finish(9, "hola mundo", [], (10, 5), "normal")

        self.assertEqual(app.scope.last_response, "hola mundo")
        self.assertEqual([m.content for m in app.docs.session.conversation], ["hola mundo"])
        self.assertEqual(app.streaming_text, "")

@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestDocumentoRecienAbierto(unittest.TestCase):
    """Tk encola <<Modified>> de forma asíncrona: cargar no es editar."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_cargar_documento_no_lo_marca_como_sucio(self):
        document = self.root / "a.md"
        document.write_text("hola mundo", encoding="utf-8")
        self.app.load_document(document)

        self._settle()

        self.assertFalse(self.app.session.dirty)
        self.assertEqual(self.app.sync_label.cget("text"), "◌  Sin cambios")

    def test_edicion_del_usuario_si_marca_como_sucio(self):
        document = self.root / "a.md"
        document.write_text("hola", encoding="utf-8")
        self.app.load_document(document)
        self._settle()

        self.app.editor.insert("end", " escrito por el usuario")
        self._settle()

        self.assertTrue(self.app.session.dirty)
        self.assertIn("Cambios sin guardar", self.app.sync_label.cget("text"))

    def test_cambiar_documento_cambia_a_la_conversacion_del_nuevo_articulo(self):
        """La conversación es por documento: cambiar de artículo no arrastra la anterior."""
        from tukul_core.models import ChatMessage

        a = self.root / "a.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        b = self.root / "b.md"
        b.write_text("TEXTO DE B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        sesion_a = self.app.session
        self.app.session.conversation.append(ChatMessage("user", "hablo del artículo A"))
        self.app.append("Tú", "hablo del artículo A")

        self.app.load_document(b)
        self._settle()

        self.assertIsNot(self.app.session, sesion_a, "Debe ser una ArticleSession nueva")
        self.assertEqual(
            self.app.session.conversation,
            [],
            "B nunca tuvo conversación propia: debe abrir vacía, no heredar la de A",
        )
        self.assertEqual(self.app.session.document_path, b.resolve())
        self.assertNotIn("artículo A", self.app.history.get("1.0", "end-1c"))

        # A conserva su turno: al volver a A (dentro de la misma corrida), se restaura.
        self.app.load_document(a)
        self._settle()
        self.assertEqual(
            [message.content for message in self.app.session.conversation],
            ["hablo del artículo A"],
        )
        self.assertIn("artículo A", self.app.history.get("1.0", "end-1c"))

    def test_abrir_un_documento_ilegible_no_toca_la_sesion(self):
        a = self.root / "a.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        self.app.load_document(a)
        self._settle()
        sesion_a = self.app.session

        with patch.object(TukulApp, "show_error"):
            ok = self.app.load_document(self.root / "no-existe.md")

        self.assertFalse(ok)
        self.assertIs(self.app.session, sesion_a, "Un fallo no debe dejar sesión a medias")
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO DE A")

    def test_la_etiqueta_del_boton_sigue_al_ambito_de_revision(self):
        a = self.root / "a.md"
        a.write_text("primera frase. segunda frase.", encoding="utf-8")
        self.app.load_document(a)
        self._settle()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar artículo")

        self.app.editor.tag_add("sel", "1.0", "1.14")
        self.app.update_context()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar selección")

        self.app.editor.tag_remove("sel", "1.0", "end")
        self.app.update_context()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar artículo")

class TestRespuestaCompletaAcotada(unittest.TestCase):
    """Media: complete() no debe cargar en memoria un cuerpo arbitrariamente grande."""

    def _perfil(self):
        return LlmProfile(provider="openai_compatible", endpoint="https://example.invalid", model="m")

    def test_content_length_gigante_se_rechaza_sin_leer_el_cuerpo(self):
        class Response:
            def __init__(self):
                self.headers = {"Content-Length": "999999999"}

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def read(self, *_args):
                raise AssertionError("No debe leerse un cuerpo ya predeclarado como excesivo")

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=Response()):
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(self._perfil(), "key", "mensaje")
        self.assertIn("mayor de lo esperado", str(ctx.exception))

    def test_la_lectura_incremental_aborta_al_superar_el_techo(self):
        from tukul_core.llm import BYTES_PER_OUTPUT_TOKEN, MAX_BODY_OVERHEAD_BYTES

        max_bytes = MAX_BODY_OVERHEAD_BYTES + BYTES_PER_OUTPUT_TOKEN
        perfil = LlmProfile(
            provider="openai_compatible", endpoint="https://example.invalid",
            model="m", max_output_tokens=1,
        )

        class Response:
            def __init__(self, cuerpo: bytes):
                self._buffer = io.BytesIO(cuerpo)

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def read(self, amt: int = -1):
                return self._buffer.read(amt)

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open",
                   return_value=Response(b"x" * (max_bytes + 4096))):
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(perfil, "key", "mensaje")
        self.assertIn("mayor de lo esperado", str(ctx.exception))

    def test_el_fallback_iterable_aborta_antes_de_acumular_el_cuerpo_entero(self):
        from tukul_core.llm import BYTES_PER_OUTPUT_TOKEN, MAX_BODY_OVERHEAD_BYTES

        max_bytes = MAX_BODY_OVERHEAD_BYTES + BYTES_PER_OUTPUT_TOKEN
        perfil = LlmProfile(
            provider="openai_compatible", endpoint="https://example.invalid",
            model="m", max_output_tokens=1,
        )

        class Response:
            def __init__(self):
                self.headers = {}

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def __iter__(self):
                yield b"x" * max_bytes
                yield b"x"
                raise AssertionError("No deben consumirse fragmentos tras exceder el techo")

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=Response()):
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(perfil, "key", "mensaje")
        self.assertIn("mayor de lo esperado", str(ctx.exception))

    def test_respuesta_dentro_del_techo_se_acepta(self):
        perfil = self._perfil()
        cuerpo = b'{"choices":[{"message":{"content":"ok"}}]}'

        class Response:
            def __init__(self):
                self.headers = {"Content-Length": str(len(cuerpo))}
                self._buffer = io.BytesIO(cuerpo)

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def read(self, amt: int = -1):
                return self._buffer.read(amt)

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=Response()):
            result = LLMClient().complete(perfil, "key", "mensaje")
        self.assertEqual(result.content, "ok")

class TestParserFindingsNoIterable(unittest.TestCase):
    def test_findings_no_lista_se_descarta_sin_recorrerla(self):
        from tukul_core.review import parse_findings

        self.assertEqual(parse_findings('{"findings":"' + "x" * 100_000 + '"}'), [])
        self.assertEqual(parse_findings('{"findings":{"a":1}}'), [])
        self.assertEqual(parse_findings('{"findings":42}'), [])
