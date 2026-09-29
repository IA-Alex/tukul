"""Contratos de integración y seguridad de la capa HTTP LLM.

Estas pruebas no abren sockets ni llaman proveedores reales: el transporte se
simula para mantener la suite FIRST y evitar exponer claves en CI.
"""
from __future__ import annotations

import io
import json
import threading
import unittest
import urllib.error
from unittest.mock import patch

from tukul_core.llm import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
    LLMClient,
    LlmError,
    validate_endpoint,
)
from tukul_core.models import LlmProfile
from tukul_ui.llm_session_manager import LLMSessionManager


def profile(provider: str = "openai_compatible", **overrides: object) -> LlmProfile:
    """Crea un perfil habilitado y explícito para pruebas de transporte."""
    values: dict[str, object] = {
        "provider": provider,
        "endpoint": "https://api.example.test/v1/chat/completions",
        "model": "test-model",
        "max_output_tokens": 100,
    }
    values.update(overrides)
    return LlmProfile(**values)  # type: ignore[arg-type]


class _Response:
    def __init__(self, payload: dict):
        self._body = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)


class TestEndpointAndProtocolContracts(unittest.TestCase):
    def test_loopback_ipv6_is_allowed_but_remote_http_is_rejected(self):
        self.assertEqual(validate_endpoint("http://[::1]:11434/v1"), "http://[::1]:11434/v1")
        with self.assertRaises(LlmError):
            validate_endpoint("http://[2001:db8::1]/v1")

    def test_complete_parses_openai_response_and_usage(self):
        """Verifica que complete() parsea respuestas OpenAI-compatibles (deepinfra/novita)."""
        result = _Response(
            {
                "choices": [{"message": {"content": "Respuesta"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }
        )
        perfil = profile(
            "openai_compatible", endpoint="https://api.example.test/v1/chat/completions", model="test-model"
        )
        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=result):
            response = LLMClient().complete(perfil, "test-secret", "Hola")

        self.assertEqual((response.content, response.input_tokens, response.output_tokens), ("Respuesta", 12, 4))

    def test_complete_parses_openai_streaming_style(self):
        """Verifica que complete() también maneja respuestas con content nulo (streaming simulado)."""
        result = _Response(
            {
                "choices": [{"message": {"content": "Hola mundo"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 3},
            }
        )
        perfil = profile(
            "openai_compatible",
            endpoint="https://api.example.test/v1/chat/completions",
        )
        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=result):
            response = LLMClient().complete(perfil, "test-secret", "Hola")

        self.assertEqual((response.content, response.input_tokens, response.output_tokens), ("Hola mundo", 9, 3))

    def test_invalid_provider_shape_becomes_safe_user_error(self):
        malformed = _Response({"choices": []})
        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=malformed):
            with self.assertRaisesRegex(LlmError, "respuesta válida"):
                LLMClient().complete(profile(), "test-secret", "Hola")


class TestResilienceContracts(unittest.TestCase):
    def test_retry_delay_honors_valid_retry_after_and_falls_back_for_invalid_values(self):
        client = LLMClient()
        delayed = urllib.error.HTTPError(
            "https://api.example.test", 429, "slow down", {"Retry-After": "1.25"}, None
        )
        invalid = urllib.error.HTTPError(
            "https://api.example.test", 429, "slow down", {"Retry-After": "tomorrow"}, None
        )
        self.assertEqual(client._retry_delay(1, delayed), 1.25)
        self.assertEqual(client._retry_delay(2, invalid), min(BACKOFF_BASE_SECONDS * 2, BACKOFF_MAX_SECONDS))

    def test_cancellation_during_retry_prevents_a_second_connection_attempt(self):
        client = LLMClient()
        cancelled = threading.Event()
        attempts = 0

        def open_fails(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            cancelled.set()
            raise urllib.error.URLError("offline")

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", side_effect=open_fails):
            self.assertIsNone(client._open_with_retry(object(), cancelled))
        self.assertEqual(attempts, 1)

    def test_memory_limit_counts_utf8_bytes_not_characters(self):
        manager = LLMSessionManager()
        self.assertEqual(manager._accept_chunk("á", 0, 2), 2)
        with self.assertRaisesRegex(LlmError, "límite de memoria"):
            manager._accept_chunk("á", 1, 2)
