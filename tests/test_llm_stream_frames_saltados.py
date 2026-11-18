"""D-2: distinguir un stream truncado por frames SSE saltados de un `[DONE]` limpio.

Cuando el proveedor cambia el esquema a mitad de stream, o un frame llega
cortado, `_consume_sse` salta el frame para no abortar la respuesta entera.
El problema no era saltarlo, sino que el salto se perdía en silencio: una
respuesta truncada quedaba indistinguible de una completa. Aquí se fija el
contrato de la constancia observable del salto.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tukul_core.llm import LLMClient, LlmProfile


def _perfil() -> LlmProfile:
    return LlmProfile(provider="openai_compatible", endpoint="http://127.0.0.1:1/v1", model="m")


def _frame(texto: str) -> bytes:
    return b"data: " + json.dumps({"choices": [{"delta": {"content": texto}}]}).encode() + b"\n"


class TestStreamConFramesSaltados(unittest.TestCase):
    """El texto válido llega íntegro y el salto deja rastro consultable."""

    def test_un_frame_malformado_no_corta_y_deja_constancia(self):
        respuesta = iter([
            _frame("Hola"),
            b"data: {esto no es json}\n",
            _frame(" mundo"),
            b"data: [DONE]\n",
        ])
        cliente = LLMClient()
        with patch("tukul_core.llm.logger") as log:
            chunks = list(cliente._consume_sse(_perfil(), respuesta, None))

        self.assertEqual([c.content for c in chunks], ["Hola", " mundo"])
        self.assertEqual(cliente.last_skipped_frames, 1)
        log.warning.assert_called_once()
        assert "1" in log.warning.call_args.args[0] % log.warning.call_args.args[1:]

    def test_un_done_limpio_no_produce_aviso_ni_cuenta(self):
        respuesta = iter([_frame("Hola"), b"data: [DONE]\n"])
        cliente = LLMClient()
        with patch("tukul_core.llm.logger") as log:
            chunks = list(cliente._consume_sse(_perfil(), respuesta, None))

        self.assertEqual([c.content for c in chunks], ["Hola"])
        self.assertEqual(cliente.last_skipped_frames, 0)
        log.warning.assert_not_called()

    def test_la_cuenta_se_reinicia_entre_peticiones(self):
        cliente = LLMClient()
        with patch("tukul_core.llm.logger"):
            list(cliente._consume_sse(_perfil(), iter([b"data: {roto}\n"]), None))
            assert cliente.last_skipped_frames == 1  # la primera petición sí contó
            list(cliente._consume_sse(_perfil(), iter([_frame("Hola")]), None))

        # La segunda petición no arrastra el salto de la primera.
        self.assertEqual(cliente.last_skipped_frames, 0)

    def test_el_aviso_no_vuelca_el_contenido_del_frame(self):
        respuesta = iter([b"data: {roto con secreto 123}\n", b"data: [DONE]\n"])
        cliente = LLMClient()
        with patch("tukul_core.llm.logger") as log:
            list(cliente._consume_sse(_perfil(), respuesta, None))

        mensaje = log.warning.call_args.args[0] % log.warning.call_args.args[1:]
        self.assertNotIn("secreto", mensaje)
        self.assertNotIn("123", mensaje)
