"""Prueba de carga opcional para un endpoint OpenAI-compatible de pruebas.

No se ejecuta con pytest. Requiere un servidor controlado y las variables:
TUKUL_LOAD_HOST (p. ej. http://127.0.0.1:8080) y, si aplica,
TUKUL_LOAD_API_KEY. Nunca apuntar a un proveedor de producción.
"""
from __future__ import annotations

import os
from uuid import uuid4

from locust import HttpUser, between, task


class TukulLlmUser(HttpUser):
    """Mide latencia y tasa de error del contrato Chat Completions."""

    host = os.environ.get("TUKUL_LOAD_HOST", "http://127.0.0.1:8080")
    wait_time = between(0.2, 1.0)

    @task
    def complete_editor_prompt(self) -> None:
        request_id = str(uuid4())
        payload = {
            "model": os.environ.get("TUKUL_LOAD_MODEL", "test-model"),
            "messages": [
                {"role": "system", "content": "Eres un editor de pruebas."},
                {"role": "user", "content": f"Revisa este borrador de carga: {request_id}"},
            ],
            "max_tokens": 32,
            "temperature": 0,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if api_key := os.environ.get("TUKUL_LOAD_API_KEY"):
            headers["Authorization"] = f"Bearer {api_key}"

        with self.client.post(
            "/v1/chat/completions", json=payload, headers=headers, name="POST /v1/chat/completions", catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
            elif not response.json().get("choices"):
                response.failure("Respuesta sin choices")
