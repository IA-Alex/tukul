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
    """El diálogo de ideas pedía la misma confirmación dos veces.

    Antes se verificaba inspeccionando el texto fuente de `app.py`; al mover el
    pipeline a `tukul_ui.ideas` esa comprobación se vuelve de comportamiento:
    se ejercita `fetch_suggestion` con un host mínimo y se cuenta cuántas veces
    se pide confirmación. Es más fuerte (mide la ejecución, no el texto) y no se
    rompe por mover o reformatear el código.
    """

    class _HostDoble:
        """Host mínimo: solo lo que `IdeasController` declara en su Protocol."""

        def __init__(self, *, habilitado: bool, key: str) -> None:
            from tukul_ui.estado import EstadoUI

            class _Status:
                def __init__(self) -> None:
                    self.mensajes: list[str] = []

                def set(self, texto: str, _detalle: str = "") -> None:
                    self.mensajes.append(texto)

            self._habilitado = habilitado
            self._key = key
            self.closing = False
            self.status = _Status()
            self._estado = EstadoUI  # referencia para tipado, no se usa

        @property
        def profile(self):
            from tukul_core.llm import LlmProfile

            # `enabled` se deriva de provider/endpoint/model.
            provider = "openai_compatible" if self._habilitado else "disabled"
            return LlmProfile(provider=provider, endpoint="http://127.0.0.1:1/v1", model="m")

        @property
        def key(self) -> str:
            return self._key

        def after(self, _ms, _func=None):
            return "after-id"

        def winfo_screenwidth(self) -> int:
            return 1920

        def winfo_screenheight(self) -> int:
            return 1080

        def append(self, *_a, **_k) -> None:
            pass

        def _upsert_context_article(self, _article) -> bool:
            return True

        def _authorize_context_articles(self) -> None:
            pass

        def _registrar_reaplicar_tema(self, _ancla, _reaplicar) -> None:
            pass

    def _controller(self, *, habilitado: bool = True, key: str = "k"):
        from pathlib import Path

        from tukul_ui.ideas import IdeasController

        host = self._HostDoble(habilitado=habilitado, key=key)
        return IdeasController(host, Path("/tmp"), 24), host

    def test_sin_llm_avisa_una_vez_y_no_arranca_worker(self):
        """Sin perfil habilitado ni key: un solo aviso, sin consultar fuentes."""
        ctrl, _host = self._controller(habilitado=False, key="")
        with patch("tukul_ui.ideas.messagebox.showinfo") as aviso, \
             patch("tukul_ui.ideas.messagebox.askyesno") as confirmar, \
             patch("tukul_ui.ideas.WorkerThreads.start") as arrancar:
            ctrl.fetch_suggestion(dialog=None, on_done=lambda: None)
        self.assertEqual(aviso.call_count, 1)
        self.assertEqual(confirmar.call_count, 0)
        arrancar.assert_not_called()

    def test_una_sola_confirmacion_antes_de_generar(self):
        """Con credenciales: exactamente una confirmación, y arranca el worker."""
        ctrl, _host = self._controller(habilitado=True, key="k")
        with patch("tukul_ui.ideas.messagebox.showinfo") as aviso, \
             patch("tukul_ui.ideas.messagebox.askyesno", return_value=False) as confirmar, \
             patch("tukul_ui.ideas.WorkerThreads.start") as arrancar:
            ctrl.fetch_suggestion(dialog=None, on_done=lambda: None)
        self.assertEqual(confirmar.call_count, 1, "Debe confirmar una sola vez.")
        self.assertEqual(aviso.call_count, 0)
        arrancar.assert_not_called()  # el usuario canceló la confirmación

    def test_confirmar_arranca_el_pipeline_una_vez(self):
        ctrl, _host = self._controller(habilitado=True, key="k")
        with patch("tukul_ui.ideas.messagebox.askyesno", return_value=True), \
             patch("tukul_ui.ideas.WorkerThreads.start") as arrancar:
            ctrl.fetch_suggestion(dialog=None, on_done=lambda: None)
        arrancar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
