"""Tests directos de LLMSessionManager: cada rama de error en aislamiento.

Complementa tests/test_cola_eventos.py (que ya cubre el camino feliz y un
error a mitad de ráfaga de punta a punta, con hilos reales). Acá se llama a
stream_response() de forma síncrona para poder ejercitar cada rama de
manejo de errores sin depender de threading ni de una ventana Tk.
"""
import json
import unittest
from unittest.mock import patch

from tukul_core.llm import LLMClient, LlmError, StreamChunk
from tukul_core.models import LlmProfile
from tukul_ui.llm_session_manager import LLMSessionManager


def _profile(**overrides) -> LlmProfile:
    base = dict(
        provider="openai_compatible",
        endpoint="https://api.example.com/v1/chat/completions",
        model="m",
        max_output_tokens=100,
    )
    base.update(overrides)
    return LlmProfile(**base)


class StreamResponseTests(unittest.TestCase):
    def setUp(self):
        self.manager = LLMSessionManager()
        self.chunks: list[str] = []
        self.errores: list[str] = []
        self.completados: list[tuple[str, tuple]] = []

    def _run(self, cancel_event=None):
        self.manager.stream_response(
            _profile(), "clave", "articulo", "paquete", [],
            on_chunk=self.chunks.append,
            on_error=self.errores.append,
            on_complete=lambda r, u: self.completados.append((r, u)),
            request_id=1,
            cancel_event=cancel_event,
        )

    def test_no_hace_nada_si_ya_esta_cancelado_al_entrar(self):
        import threading
        evento = threading.Event()
        evento.set()

        self._run(cancel_event=evento)

        self.assertEqual(self.chunks, [])
        self.assertEqual(self.errores, [])
        self.assertEqual(self.completados, [])

    def test_prompt_invalido_reporta_error_sin_tocar_la_red(self):
        with patch(
            "tukul_ui.llm_session_manager.build_editor_prompt",
            side_effect=ValueError("artículo demasiado grande"),
        ):
            self._run()

        self.assertEqual(len(self.errores), 1)
        self.assertIn("Error al preparar prompt", self.errores[0])
        self.assertEqual(self.completados, [])

    def test_respuesta_vacia_se_reporta_como_error(self):
        with patch.object(LLMClient, "stream", lambda *a, **k: iter([StreamChunk("")])):
            self._run()

        self.assertEqual(len(self.errores), 1)
        self.assertIn("respuesta vacía", self.errores[0])

    def test_cancelado_a_mitad_de_stream_no_llama_ningun_callback(self):
        import threading
        evento = threading.Event()

        def flujo(self, profile, api_key, prompt, rid=None, cancel_event=None):
            yield StreamChunk("un poco")
            evento.set()  # se cancela DESPUÉS del primer chunk, antes del próximo check
            yield StreamChunk("más")

        with patch.object(LLMClient, "stream", flujo):
            self._run(cancel_event=evento)

        self.assertEqual(self.chunks, ["un poco"])
        self.assertEqual(self.errores, [], "Cancelado no es un error")
        self.assertEqual(self.completados, [])

    def test_llm_error_del_proveedor_se_reporta_tal_cual(self):
        def flujo(self, profile, api_key, prompt, rid=None, cancel_event=None):
            raise LlmError("La API key fue rechazada.")
            yield  # pragma: no cover - hace de esta función un generador

        with patch.object(LLMClient, "stream", flujo):
            self._run()

        self.assertEqual(self.errores, ["La API key fue rechazada."])

    def test_error_de_red_o_parsing_incluye_la_clase_de_excepcion(self):
        def flujo(self, profile, api_key, prompt, rid=None, cancel_event=None):
            raise json.JSONDecodeError("bad json", "doc", 0)
            yield  # pragma: no cover

        with patch.object(LLMClient, "stream", flujo):
            self._run()

        self.assertEqual(len(self.errores), 1)
        self.assertIn("JSONDecodeError", self.errores[0])

    def test_excepcion_inesperada_no_tumba_el_hilo_worker(self):
        def flujo(self, profile, api_key, prompt, rid=None, cancel_event=None):
            raise RuntimeError("algo que nadie previó")
            yield  # pragma: no cover

        with patch.object(LLMClient, "stream", flujo):
            self._run()  # no debe propagar la excepción

        self.assertEqual(len(self.errores), 1)
        self.assertIn("Error interno inesperado", self.errores[0])

    def test_respuesta_que_excede_el_techo_de_memoria_se_trunca(self):
        perfil = _profile(max_output_tokens=1)  # techo mínimo: 2MB por el piso fijo

        def flujo(self, profile, api_key, prompt, rid=None, cancel_event=None):
            # Un solo chunk mayor al piso de 2MB fuerza el límite de _accept_chunk.
            yield StreamChunk("x" * (3 * 1024 * 1024))

        with patch.object(LLMClient, "stream", flujo):
            self.manager.stream_response(
                perfil, "clave", "articulo", "paquete", [],
                on_chunk=self.chunks.append,
                on_error=self.errores.append,
                on_complete=lambda r, u: self.completados.append((r, u)),
                request_id=1,
            )

        self.assertEqual(len(self.errores), 1)
        self.assertIn("límite de memoria", self.errores[0])


class CancelTests(unittest.TestCase):
    def test_cancel_cierra_el_stream_del_request_pedido(self):
        """`cancel` delega en el cliente y no toca ningún evento propio.

        El evento de cancelación es de la petición y lo guarda `TukulApp`; si
        el manager marcara uno suyo, cancelar marcaría el de la última petición
        lanzada en vez del de la cancelada.
        """
        manager = LLMSessionManager()

        with patch.object(LLMClient, "cancel") as cancel_cliente:
            manager.cancel(request_id=7)

        cancel_cliente.assert_called_once_with(7)

    def test_cancel_sin_evento_activo_no_falla(self):
        manager = LLMSessionManager()
        with patch.object(LLMClient, "cancel") as cancel_cliente:
            manager.cancel(request_id=1)
        cancel_cliente.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
