"""«Probar conexión»: una clave rechazada se explica antes de enviar nada.

El botón existe para romper el ciclo «guardo → no responde → cambio cosas a
ciegas». La prueba usa un servidor HTTP local que devuelve 401, así que no
necesita red ni credenciales reales.
"""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core.llm import LLMClient, LlmError
from tukul_core.models import LlmProfile


class _Rechaza(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": {"code": "invalid_api_key"}}).encode())

    def log_message(self, *args):
        pass


class TestPruebaDeConexion(unittest.TestCase):
    def setUp(self):
        self.servidor = HTTPServer(("127.0.0.1", 0), _Rechaza)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        puerto = self.servidor.server_address[1]
        self.perfil = LlmProfile(
            name="prueba", provider="openai_compatible",
            endpoint=f"http://127.0.0.1:{puerto}/v1/chat/completions",
            model="m", api_key_env="X",
        )

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()

    def test_una_clave_rechazada_dice_que_es_la_clave(self):
        with self.assertRaises(LlmError) as ctx:
            for _ in LLMClient().stream(self.perfil, "sk-mala", "ok"):
                pass
        self.assertIn("API key fue rechazada", str(ctx.exception))

    def test_sin_clave_la_prueba_no_llega_a_red(self):
        with self.assertRaises(LlmError) as ctx:
            for _ in LLMClient().stream(self.perfil, "", "ok"):
                pass
        self.assertIn("Configura endpoint, modelo y API key", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
