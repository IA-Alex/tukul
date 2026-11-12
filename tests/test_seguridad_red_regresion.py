"""Regresiones de la auditoría estructural — seguridad de red y credenciales.

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


class TestSeguridadDelEndpoint(unittest.TestCase):
    def test_acepta_https(self):
        self.assertEqual(
            validate_endpoint("https://api.deepseek.com/chat/completions"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_acepta_http_solo_en_loopback(self):
        validate_endpoint("http://localhost:11434/v1/chat/completions")
        validate_endpoint("http://127.0.0.1:11434/v1/chat/completions")

    def test_rechaza_http_remoto(self):
        with self.assertRaises(LlmError) as ctx:
            validate_endpoint("http://api-remoto.example/v1/chat/completions")
        self.assertIn("https", str(ctx.exception))

    def test_rechaza_esquemas_no_http(self):
        for endpoint in ("file:///etc/passwd", "ftp://host/x", "no-es-una-url"):
            with self.assertRaises(LlmError):
                validate_endpoint(endpoint)

    def test_la_peticion_no_se_construye_con_endpoint_inseguro(self):
        profile = LlmProfile(
            provider="openai_compatible",
            endpoint="http://exfiltra.example/v1/chat/completions",
            model="m",
        )
        with self.assertRaises(LlmError):
            LLMClient()._request(profile, "SECRETO", "hola", stream=False)

class TestLecturaSSEAcotada(unittest.TestCase):
    def test_readline_recibe_un_tope_de_bytes(self):
        from tukul_core.llm import MAX_SSE_LINE_BYTES

        recibidos = []

        class Response:
            def readline(self, limit=-1):
                recibidos.append(limit)
                return b"" if len(recibidos) > 1 else b'data: {"choices":[{"delta":{"content":"x"}}]}\n'

        lineas = list(LLMClient._iter_lines(Response()))

        self.assertEqual(len(lineas), 1)
        self.assertEqual(set(recibidos), {MAX_SSE_LINE_BYTES})

    def test_cae_a_iteracion_si_no_hay_readline(self):
        class Response:
            def __iter__(self):
                return iter((b"data: uno\n", b"data: dos\n"))

        self.assertEqual(len(list(LLMClient._iter_lines(Response()))), 2)

class TestNoRedireccionDeCredenciales(unittest.TestCase):
    """Alta: urlopen sigue 3xx conservando Authorization/x-api-key/x-goog-api-key.

    Un endpoint comprometido, mal configurado o controlado por un atacante
    podría redirigir a otro origen y robar la API key. El cliente debe fallar
    ante el 3xx sin contactar jamás con el destino redirigido.
    """

    def test_el_handler_de_redireccion_jamas_devuelve_un_seguimiento(self):
        from tukul_core.http_safety import _NoRedirectHandler

        handler = _NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                object(), None, 302, "Moved",
                {"Location": "https://otro-origen.example/x"},
                "https://otro-origen.example/x",
            )
        )

    def test_un_302_real_no_reenvia_la_api_key_al_origen_redirigido(self):
        recibido: dict[str, str] = {}

        class Destino(BaseHTTPRequestHandler):
            def _registrar(self):
                recibido["authorization"] = str(self.headers.get("Authorization"))
                recibido["x-api-key"] = str(self.headers.get("x-api-key"))
                recibido["x-goog-api-key"] = str(self.headers.get("x-goog-api-key"))

            def do_POST(self):
                self._registrar()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')

            def do_GET(self):
                # Si la corrección se revierte, el 302 se sigue como GET (con la
                # cabecera de autenticación copiada) y la key llega hasta aquí.
                self._registrar()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')

            def log_message(self, *_args):
                pass

        destino = ThreadingHTTPServer(("127.0.0.1", 0), Destino)
        hilo_destino = threading.Thread(target=destino.serve_forever, daemon=True)
        hilo_destino.start()

        class Redirige(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{destino.server_port}/v1/chat/completions",
                )
                self.end_headers()

            def log_message(self, *_args):
                pass

        redirige = ThreadingHTTPServer(("127.0.0.1", 0), Redirige)
        hilo_redirige = threading.Thread(target=redirige.serve_forever, daemon=True)
        hilo_redirige.start()

        try:
            profile = LlmProfile(
                provider="openai_compatible",
                endpoint=f"http://127.0.0.1:{redirige.server_port}/v1/chat/completions",
                model="m",
            )
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(profile, "KEY-SECRETA-DE-PRUEBA", "hola")
            self.assertIn("302", str(ctx.exception))
            self.assertEqual(
                recibido, {}, "El destino de la redirección no debe recibir la API key"
            )
        finally:
            redirige.shutdown()
            destino.shutdown()
            redirige.server_close()
            destino.server_close()

class TestCredenciales(unittest.TestCase):
    def test_delete_key_es_silenciosa_sin_llavero(self):
        original = storage.keyring
        storage.keyring = None
        try:
            storage.delete_key("cualquiera")  # no debe lanzar
        finally:
            storage.keyring = original

    def test_delete_key_revoca_en_el_llavero(self):
        original = storage.keyring
        storage.keyring = Mock()
        try:
            storage.delete_key("perfil")
            storage.keyring.delete_password.assert_called_once_with(
                "tukul", "perfil"
            )
        finally:
            storage.keyring = original

    def test_delete_key_propaga_fallos_reales_del_llavero(self):
        original = storage.keyring
        storage.keyring = Mock()
        storage.keyring.delete_password.side_effect = OSError("backend caído")
        try:
            with self.assertRaises(OSError):
                storage.delete_key("perfil")
        finally:
            storage.keyring = original
