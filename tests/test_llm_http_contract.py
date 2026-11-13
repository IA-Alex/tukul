"""Contrato HTTP real del cliente LLM, contra un servidor local.

Los tests existentes ejercitan `LLMClient` con dobles: cubren el parseo, pero
no el transporte. Un cambio de cabecera (p. ej. `x-goog-api-key` por
`Authorization`), de ruta de retry o del manejo de un 3xx pasaría los tests
actuales y rompería la aplicación contra el proveedor real.

Aquí se levanta `ThreadingHTTPServer` en `127.0.0.1:0` y se observa lo que
realmente sale por el cable: cuerpo, cabeceras, número de intentos y a qué
host se llega. Sin red externa; el conjunto tarda milisegundos.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tukul_core.llm import (
    PROVIDERS,
    LLMClient,
    LlmError,
    LlmProfile,
    ProviderSpec,
    http_error_message,
)

# `PROVIDERS` solo registra los que la UI ofrece hoy (OpenAI-compatible,
# DeepInfra y Novita): los tres hablan el mismo protocolo. Para ejercitar las
# ramas de Anthropic y Gemini se registran aquí, y se retiran al terminar, en
# lugar de añadirlos a la UI sin una decisión de producto.
_PROTOCOLOS_DE_PRUEBA = {
    "anthropic_prueba": ProviderSpec(
        "anthropic_prueba", "Anthropic (prueba)", "https://api.anthropic.com/v1/messages",
        protocol="anthropic_messages",
    ),
    "gemini_prueba": ProviderSpec(
        "gemini_prueba", "Gemini (prueba)", "https://generativelanguage.googleapis.com/v1beta",
        protocol="gemini_generate_content",
    ),
}



class _ServidorLocal:
    """Servidor HTTP de un solo comportamiento, con registro de peticiones.

    `responder` recibe el handler de `BaseHTTPRequestHandler` ya con la
    petición registrada en `peticiones`, y escribe la respuesta.
    """

    def __init__(self, responder) -> None:
        self.peticiones: list[dict[str, Any]] = []
        # Nº de respuestas cuya escritura aún no ha terminado.
        self.escrituras_abiertas: int = 0
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # silencia el log de http.server
                pass

            def _escribir(self, *partes: bytes) -> None:
                """Escribe por el socket, ignorando si el cliente ya se fue."""
                self.log_message = lambda *a, **k: None
                for parte in partes:
                    try:
                        self.wfile.write(parte)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return

            def _responder(self) -> None:
                longitud = int(self.headers.get("Content-Length") or 0)
                cuerpo = self.rfile.read(longitud) if longitud else b""
                separada = urllib.parse.urlsplit(self.path)
                servidor.peticiones.append(
                    {
                        "path": separada.path,
                        "query": separada.query,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": cuerpo,
                    }
                )
                servidor.escrituras_abiertas += 1
                try:
                    responder(self)
                finally:
                    servidor.escrituras_abiertas -= 1

            # http.server despacha según el nombre: son parte de su API.
            do_GET = _responder  # noqa: N815
            do_POST = _responder  # noqa: N815

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.hilo.start()

    @property
    def url(self) -> str:
        host, puerto = self.httpd.server_address[:2]
        return f"http://{host}:{puerto}"

    def completar_escrituras(self, timeout: float = 5.0) -> None:
        """Espera a que ninguna respuesta siga escribiéndose."""
        limite = time.monotonic() + timeout
        while self.escrituras_abiertas and time.monotonic() < limite:
            time.sleep(0.02)

    def cerrar(self) -> None:
        self.httpd.daemon_threads = True
        self.httpd.block_on_close = False
        self.httpd.shutdown()
        self.httpd.server_close()
        self.hilo.join(timeout=5)


def _perfil(endpoint: str, provider: str = "openai_compatible", **extra) -> LlmProfile:
    return LlmProfile(provider=provider, endpoint=endpoint, model="modelo-de-prueba", **extra)


class TestStreamingContraServidorReal(unittest.TestCase):
    """SSE genuino: cabeceras, cuerpo y eventos tal como los envía el cable."""

    def setUp(self) -> None:
        def responder(self: BaseHTTPRequestHandler) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for linea in (
                b'data: {"choices":[{"delta":{"content":"Ho"}}]}\n',
                b': comentario SSE que debe ignorarse\n',
                b'data: {"choices":[{"delta":{"content":"la"}}]}\n',
                b'data: {"choices":[{"delta":{}}],'
                b'"usage":{"prompt_tokens":11,"completion_tokens":2}}\n',
                b"data: [DONE]\n",
            ):
                self._escribir(linea)

        self.servidor = _ServidorLocal(responder)

    def tearDown(self) -> None:
        self.servidor.cerrar()

    def test_stream_emite_el_texto_y_el_usage_del_cable(self):
        chunks = list(LLMClient().stream(_perfil(self.servidor.url), "clave-real", "hola"))

        self.assertEqual("".join(c.content for c in chunks), "Hola")
        self.assertEqual(
            (chunks[-1].input_tokens, chunks[-1].output_tokens), (11, 2)
        )

    def test_la_peticion_lleva_la_key_y_el_stream_activado(self):
        list(LLMClient().stream(_perfil(self.servidor.url), "clave-real", "hola"))

        peticion = self.servidor.peticiones[0]
        self.assertEqual(peticion["path"], "/")
        self.assertEqual(peticion["headers"]["authorization"], "Bearer clave-real")
        self.assertEqual(peticion["headers"]["accept"], "text/event-stream")
        cuerpo = json.loads(peticion["body"])
        self.assertTrue(cuerpo["stream"])
        self.assertEqual(cuerpo["model"], "modelo-de-prueba")
        self.assertEqual(cuerpo["messages"][1]["content"], "hola")


class TestReintentosContraServidorReal(unittest.TestCase):
    """429 con `Retry-After` real: se reintenta y se espera lo que pide."""

    def setUp(self) -> None:
        estado = {"intentos": 0}

        def responder(self: BaseHTTPRequestHandler) -> None:
            estado["intentos"] += 1
            if estado["intentos"] == 1:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self._escribir(b'{"choices":[{"message":{"content":"listo"}}]}')

        self.estado = estado
        self.servidor = _ServidorLocal(responder)

    def tearDown(self) -> None:
        self.servidor.cerrar()

    def test_complete_reintenta_tras_el_retry_after_y_lo_acota(self):
        inicio = time.monotonic()
        respuesta = LLMClient().complete(_perfil(self.servidor.url), "k", "hola")
        transcurrido = time.monotonic() - inicio

        self.assertEqual(respuesta.content, "listo")
        self.assertEqual(len(self.servidor.peticiones), 2)
        # `Retry-After: 1` se respeta pero nunca por encima de BACKOFF_MAX_SECONDS.
        self.assertGreaterEqual(transcurrido, 0.9)
        self.assertLess(transcurrido, 5.0)


class TestSinSeguirRedireccionesContraServidorReal(unittest.TestCase):
    """Un 302 no puede reenviar la credencial al destino redirigido."""

    def setUp(self) -> None:
        def destino(self: BaseHTTPRequestHandler) -> None:
            self.send_response(200)
            self.end_headers()
            self._escribir(b'{"choices":[{"message":{"content":"filtrado"}}]}')

        def redirigir(self: BaseHTTPRequestHandler) -> None:
            self.send_response(302)
            self.send_header("Location", destino_url)
            self.end_headers()

        self.destino_servidor = _ServidorLocal(destino)
        destino_url = f"{self.destino_servidor.url}/robar"
        self.origen = _ServidorLocal(redirigir)

    def tearDown(self) -> None:
        self.origen.cerrar()
        self.destino_servidor.cerrar()

    def test_el_302_llega_como_error_sin_tocar_el_destino(self):
        with self.assertRaises(LlmError):
            LLMClient().complete(_perfil(self.origen.url), "clave-secreta", "hola")

        self.assertEqual(len(self.origen.peticiones), 1)
        self.assertEqual(
            self.destino_servidor.peticiones, [],
            "La redirección se siguió y la API key llegó a otro origen",
        )


class TestTechoDeRespuestaContraServidorReal(unittest.TestCase):
    """Un cuerpo mayor que el techo se corta antes de cargarlo en memoria."""

    def setUp(self) -> None:
        def responder(self: BaseHTTPRequestHandler) -> None:
            cuerpo = b"x" * (2 * 1024 * 1024)
            self.send_response(200)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self._escribir(cuerpo)

        self.servidor = _ServidorLocal(responder)

    def tearDown(self) -> None:
        # Primero se deja terminar la respuesta; `shutdown()` con una escritura
        # viva bloquea el hilo principal y, con el recolector en marcha en otro
        # hilo, CPython aborta.
        self.servidor.completar_escrituras(timeout=5)
        self.servidor.cerrar()

    def test_cuerpo_gigante_falla_con_error_legible(self):
        perfil = _perfil(self.servidor.url, max_output_tokens=1000)
        with self.assertRaises(LlmError) as ctx:
            LLMClient().complete(perfil, "k", "hola")
        self.assertIn("mayor de lo esperado", str(ctx.exception))
        # Regresión: el cliente debe drenar el cuerpo rechazado. Si cierra a
        # medias, el servidor se queda bloqueado escribiendo en el socket y
        # `shutdown()` (y el cierre del proceso) espera a un cliente fantasma.
        self.servidor.completar_escrituras(timeout=5)
        self.assertFalse(
            self.servidor.escrituras_abiertas,
            "El servidor quedó atascado escribiendo un cuerpo que nadie lee",
        )


class TestCabecerasPorProtocoloContraServidorReal(unittest.TestCase):
    """Cada protocolo usa SU cabecera de credencial, no solo el parseo."""

    def setUp(self) -> None:
        PROVIDERS.update(_PROTOCOLOS_DE_PRUEBA)

        def responder(self: BaseHTTPRequestHandler) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Un cuerpo mínimamente compatible: aquí interesa la petición.
            self._escribir(b'{"choices":[{"message":{"content":"ok"}}]}')

        self.servidor = _ServidorLocal(responder)

    def tearDown(self) -> None:
        for clave in _PROTOCOLOS_DE_PRUEBA:
            PROVIDERS.pop(clave, None)
        self.servidor.cerrar()

    def test_openai_compatible_usa_authorization_bearer(self):
        LLMClient().complete(_perfil(self.servidor.url), "k-openai", "hola")
        cabeceras = self.servidor.peticiones[0]["headers"]
        self.assertEqual(cabeceras["authorization"], "Bearer k-openai")
        self.assertNotIn("x-api-key", cabeceras)

    def test_anthropic_usa_x_api_key_y_su_version(self):
        perfil = LlmProfile(
            provider="anthropic_prueba",
            endpoint=self.servidor.url,
            model="modelo-de-prueba",
        )
        with self.assertRaises(LlmError):
            LLMClient().complete(perfil, "k-anthropic", "hola")
        cabeceras = self.servidor.peticiones[0]["headers"]
        self.assertEqual(cabeceras["x-api-key"], "k-anthropic")
        self.assertEqual(cabeceras["anthropic-version"], "2023-06-01")
        self.assertNotIn("authorization", cabeceras)

    def test_gemini_usa_x_goog_api_key(self):
        perfil = LlmProfile(
            provider="gemini_prueba",
            endpoint=self.servidor.url,
            model="modelo-de-prueba",
        )
        with self.assertRaises(LlmError):
            LLMClient().complete(perfil, "k-gemini", "hola")
        cabeceras = self.servidor.peticiones[0]["headers"]
        self.assertEqual(cabeceras["x-goog-api-key"], "k-gemini")
        self.assertNotIn("authorization", cabeceras)


class TestMensajeDeErrorDelProveedorContraServidorReal(unittest.TestCase):
    """Un error HTTP debe propagar el `error.message` que envía el proveedor.

    Antes solo se traducía por código de estado, así que un 400 por «modelo
    inexistente» y un 400 por «contexto excedido» llegaban iguales. El cuerpo del
    error es dato no confiable: se lee con techo y cualquier desvío cae al
    mensaje por código.
    """

    def _servidor_con_error(self, cuerpo: bytes) -> _ServidorLocal:
        def responder(self: BaseHTTPRequestHandler) -> None:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self._escribir(cuerpo)

        return _ServidorLocal(responder)

    def test_400_propaga_el_mensaje_del_proveedor(self):
        servidor = self._servidor_con_error(
            b'{"error":{"message":"model not found: deepseek-ai/Inexistente",'
            b'"type":"invalid_request_error","code":"model_not_found"}}'
        )
        try:
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(_perfil(servidor.url), "k", "hola")
        finally:
            servidor.cerrar()
        self.assertEqual(str(ctx.exception), "model not found: deepseek-ai/Inexistente")

    def test_400_sin_mensaje_cae_al_texto_por_codigo(self):
        servidor = self._servidor_con_error(b'{"error":{"type":"x"}}')
        try:
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(_perfil(servidor.url), "k", "hola")
        finally:
            servidor.cerrar()
        self.assertEqual(str(ctx.exception), http_error_message(400))

    def test_400_con_cuerpo_no_json_cae_al_texto_por_codigo(self):
        servidor = self._servidor_con_error(b"<html>Bad Request</html>")
        try:
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(_perfil(servidor.url), "k", "hola")
        finally:
            servidor.cerrar()
        self.assertIn("HTTP 400", str(ctx.exception))

    def test_el_mensaje_del_proveedor_se_acota_en_longitud(self):
        largo = b"x" * 5000
        servidor = self._servidor_con_error(b'{"error":{"message":"' + largo + b'"}}')
        try:
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(_perfil(servidor.url), "k", "hola")
        finally:
            servidor.cerrar()
        self.assertLessEqual(len(str(ctx.exception)), 500)


if __name__ == "__main__":
    unittest.main()
