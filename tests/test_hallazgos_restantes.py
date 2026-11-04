"""Hallazgos del roadmap de la auditoría 2026-11-04: regresiones del arreglo.

Cada test corresponde a un defecto concreto con su evidencia, para que no
vuelva sin que alguien lo note.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from unittest.mock import patch

from tukul_core.llm import LLMClient, LlmProfile


def _perfil(endpoint: str = "http://127.0.0.1:1/v1", **extra) -> LlmProfile:
    return LlmProfile(
        provider="openai_compatible",
        endpoint=endpoint,
        model="m",
        **extra,
    )


class TestCancelarDuranteElBackoff(unittest.TestCase):
    """M3: `time.sleep` en el reintento dejaba el botón Cancelar muerto 4 s.

    Con `time.sleep`, cancelar durante la espera entre intentos no se notaba
    hasta que la espera terminaba. El worker seguía ocupado y la UI decía
    "cancelado" con un hilo todavía vivo detrás.
    """

    def test_cancelar_durante_la_espera_corta_el_envio_de_inmediato(self):
        import urllib.error

        cancel = threading.Event()
        error = urllib.error.URLError("sin red")

        def abrir(*_args, **_kwargs):
            cancel.set()  # el usuario cancela mientras se intenta conectar
            raise error

        inicio = time.monotonic()
        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", side_effect=abrir), \
             patch("tukul_core.llm.BACKOFF_BASE_SECONDS", 5.0):
            resultado = LLMClient()._open_with_retry(object(), cancel)
        transcurrido = time.monotonic() - inicio

        self.assertIsNone(resultado, "Cancelado: no debe haber respuesta")
        self.assertLess(transcurrido, 1.0, "La cancelación no interrumpió la espera")

    def test_sin_cancelacion_la_espera_se_respeta(self):
        import urllib.error

        intentos = {"n": 0}

        def abrir(*_args, **_kwargs):
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise urllib.error.URLError("sin red")
            raise urllib.error.HTTPError("http://127.0.0.1:1/", 401, "Unauthorized", {}, None)

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", side_effect=abrir), \
             patch("tukul_core.llm.time.sleep") as dormir:
            with self.assertRaises(urllib.error.HTTPError):
                LLMClient()._open_with_retry(object(), None)
        dormir.assert_called_once()


class TestRespuestaConToolCalls(unittest.TestCase):
    """M6: una respuesta con `tool_calls` se veía como texto vacío.

    Tukul no expone herramientas, pero el modelo puede pedirlas igualmente. Sin
    un tipo que las represente, el delta llegaba como `None` y la respuesta se
    descartaba o se mostraba como "vacía", sin rastro de la causa.
    """

    def test_el_delta_con_tool_calls_se_representa_y_lo_ve_el_log(self):
        cliente = LLMClient()
        evento = {
            "choices": [{
                "delta": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "borrar_archivos", "arguments": "{}"},
                    }],
                },
            }],
        }
        chunk = cliente._stream_event(_perfil(), evento)

        self.assertEqual(chunk.content, "")
        self.assertEqual(
            [(llamada.id, llamada.name) for llamada in chunk.tool_calls],
            [("call_1", "borrar_archivos")],
        )
        # El consumidor registra el intento: no se ejecuta nada, pero se sabe.
        respuesta = iter([b'data: ' + __import__("json").dumps(evento).encode() + b"\n"])
        with patch("tukul_core.llm.logger") as log_consumo:
            list(cliente._consume_sse(_perfil(), respuesta, None))
        log_consumo.warning.assert_called_once()

    def test_un_delta_normal_no_se_marca_como_tool_call(self):
        chunk = LLMClient()._stream_event(
            _perfil(), {"choices": [{"delta": {"content": "Hola"}}]}
        )
        self.assertEqual(chunk.tool_calls, ())
        self.assertEqual(chunk.content, "Hola")


class TestConfirmacionUnicaDelDialogoDeIdeas(unittest.TestCase):
    """El diálogo de ideas pedía la misma confirmación dos veces."""

    def test_solo_hay_una_confirmacion_y_un_aviso_en_la_fuente(self):
        from pathlib import Path

        fuente = (Path(__file__).parent.parent / "tukul_ui" / "app.py").read_text(
            encoding="utf-8")
        inicio = fuente.index("def _fetch_impact_suggestion(")
        fin = fuente.index("def _ejecutar_pipeline_ideas(")
        cuerpo = fuente[inicio:fin]
        self.assertEqual(cuerpo.count("messagebox.askyesno("), 1)
        self.assertEqual(cuerpo.count("messagebox.showinfo("), 1)


if __name__ == "__main__":
    unittest.main()
