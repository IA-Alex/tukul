"""Garantías de la arquitectura de eventos worker → interfaz.

Sustituye a tests/test_integration_real_events.py, que reimplementaba el bombeo
a mano ("# Simulamos finish()") y afirmaba sobre atributos inexistentes en
producción (`chunk_queue`, `partial_output`): no podía detectar ningún fallo real.

Cada prueba de aquí ejecuta el código de producción: ChunkBuffer, la cola de
control, process_ui_events(), _render_pending_chunks() y finish().

Invariantes bajo prueba:
- Una finalización (`complete`/`error`) nunca se pierde ni bloquea al worker,
  por muy larga que sea la ráfaga de texto que la precede.
- Ningún fragmento recibido se pierde: se coalesce, no se descarta.
- El texto pendiente se pinta ANTES de que su finalización cierre la petición.
"""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from articulador_core.llm import LLMClient, StreamChunk
from articulador_core.models import ArticleSession, LlmProfile
from articulador_ui.app import ArticuladorApp
from articulador_ui.chunk_buffer import ChunkBuffer
from articulador_ui.document_scope import DocumentScope
from articulador_ui.estado import EstadoUI
from articulador_ui.llm_session_manager import LLMSessionManager


class _Var:
    """StringVar mínimo: los ayudantes sin ventana no tienen raíz Tk."""

    def __init__(self, valor: str = "") -> None:
        self._valor = valor

    def set(self, valor) -> None:
        self._valor = valor

    def get(self):
        return self._valor


def _app_sin_ventana() -> ArticuladorApp:
    """ArticuladorApp con los canales reales y los widgets simulados."""
    app = ArticuladorApp.__new__(ArticuladorApp)
    app.closing = False
    app.control_queue = queue.Queue()
    app.chunks = ChunkBuffer()
    app.request_types = {}
    app.streaming_request = None
    app.streaming_text = ""
    app.scope = DocumentScope()
    app.estado_actual = EstadoUI.REPOSO
    app.activity = _Var(EstadoUI.REPOSO.etiqueta())
    app.estado_ayuda = _Var(EstadoUI.REPOSO.ayuda)
    app.estado_label = Mock()

    def _pintar(request_id: int, texto: str) -> None:
        """Refleja la contabilidad de stream_chunk() sin tocar widgets Tk.

        La versión real acumula en `streaming_text`, y de ahí sale la salida
        parcial que finish() conserva cuando el streaming acaba en error.
        """
        if app.streaming_request != request_id:
            app.streaming_request = request_id
            app.streaming_text = ""
        app.streaming_text += texto

    app.stream_chunk = Mock(side_effect=_pintar)
    for nombre in ("history", "activity", "status", "cost_label", "send_button",
                   "cancel_button", "after"):
        setattr(app, nombre, Mock())
    app.docs = Mock()
    app.docs.session = ArticleSession()
    return app


class TestBufferDeChunks(unittest.TestCase):
    """El canal de texto: no bloquea, no pierde, coalesce."""

    def test_no_pierde_ningun_fragmento(self):
        buffer = ChunkBuffer()
        piezas = [f"<{i}>" for i in range(5000)]
        for pieza in piezas:
            buffer.append(1, pieza)

        self.assertEqual(buffer.take(1), "".join(piezas))
        self.assertEqual(buffer.take(1), "", "Extraer vacía lo pendiente")

    def test_coalesce_la_rafaga_en_una_sola_entrega(self):
        buffer = ChunkBuffer()
        for i in range(1000):
            buffer.append(7, str(i))

        entregas = buffer.take_all()

        self.assertEqual(len(entregas), 1, "Una entrega por petición, no 1000")
        self.assertEqual(entregas[0][0], 7)
        self.assertEqual(entregas[0][1], "".join(str(i) for i in range(1000)))

    def test_separa_el_texto_de_cada_peticion(self):
        buffer = ChunkBuffer()
        buffer.append(1, "uno-")
        buffer.append(2, "dos-")
        buffer.append(1, "uno")
        buffer.append(2, "dos")

        entregas = dict(buffer.take_all())

        self.assertEqual(entregas, {1: "uno-uno", 2: "dos-dos"})

    def test_descartar_solo_afecta_a_su_peticion(self):
        buffer = ChunkBuffer()
        buffer.append(1, "se va")
        buffer.append(2, "se queda")

        buffer.discard(1)

        self.assertEqual(dict(buffer.take_all()), {2: "se queda"})

    def test_es_seguro_entre_hilos(self):
        buffer = ChunkBuffer()
        productores = 8
        por_productor = 2000

        def producir(indice: int) -> None:
            for _ in range(por_productor):
                buffer.append(indice, "x")

        hilos = [threading.Thread(target=producir, args=(i,)) for i in range(productores)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()

        entregas = dict(buffer.take_all())
        self.assertEqual(len(entregas), productores)
        for indice in range(productores):
            self.assertEqual(len(entregas[indice]), por_productor)

    def test_extraer_mientras_se_produce_no_pierde_texto(self):
        """Consumidor y productor concurrentes: la suma debe cuadrar."""
        buffer = ChunkBuffer()
        total = 20_000
        recogido = []
        fin = threading.Event()

        def producir() -> None:
            for _ in range(total):
                buffer.append(1, "x")
            fin.set()

        hilo = threading.Thread(target=producir)
        hilo.start()
        while not fin.is_set() or buffer.pending_requests():
            recogido.append(buffer.take(1))
        hilo.join()
        recogido.append(buffer.take(1))

        self.assertEqual(len("".join(recogido)), total, "No debe perderse ni un fragmento")


class TestColaDeControlGarantizada(unittest.TestCase):
    """Una finalización nunca se pierde ni bloquea detrás de una ráfaga."""

    def test_la_cola_de_control_no_tiene_tope(self):
        app = _app_sin_ventana()
        # Con la cola única de 1000, la inserción 1001 bloqueaba al worker.
        for i in range(5000):
            app.control_queue.put_nowait(("error", i, "x", []))
        self.assertEqual(app.control_queue.qsize(), 5000)

    def test_una_rafaga_de_chunks_no_retrasa_la_finalizacion(self):
        app = _app_sin_ventana()
        app.request_types[1] = "normal"

        # Ráfaga enorme por el canal de texto…
        for _ in range(50_000):
            app.chunks.append(1, "x")
        # …y la finalización por el canal de control.
        app.control_queue.put_nowait(("complete", 1, "resultado", [], (None, None), "normal"))

        app.process_ui_events()

        self.assertEqual(app.control_queue.qsize(), 0, "El complete se procesó en el mismo ciclo")
        self.assertNotIn(1, app.request_types, "La petición quedó cerrada")

    def test_publicar_una_finalizacion_no_bloquea_al_worker(self):
        """El worker debe poder cerrar aunque la interfaz no haya drenado nada."""
        app = _app_sin_ventana()
        app.request_types[1] = "normal"
        for _ in range(100_000):
            app.chunks.append(1, "y")

        inicio = time.monotonic()
        app.control_queue.put_nowait(("complete", 1, "r", [], (None, None), "normal"))
        transcurrido = time.monotonic() - inicio

        self.assertLess(transcurrido, 0.5, "put_nowait sobre cola sin tope no puede bloquear")

    def test_la_finalizacion_ve_todo_el_texto_previo(self):
        """Orden garantizado: el texto se pinta antes de cerrar la petición."""
        app = _app_sin_ventana()
        app.request_types[1] = "normal"
        for pieza in ("Hola", " ", "mundo"):
            app.chunks.append(1, pieza)
        app.control_queue.put_nowait(("complete", 1, "Hola mundo", [], (None, None), "normal"))

        app.process_ui_events()

        pintado = "".join(llamada[0][1] for llamada in app.stream_chunk.call_args_list)
        self.assertEqual(pintado, "Hola mundo", "Nada de lo recibido puede quedar sin pintar")

    def test_el_texto_que_llega_con_el_complete_tampoco_se_pierde(self):
        """Chunks añadidos justo antes de despachar el complete, en el mismo ciclo."""
        app = _app_sin_ventana()
        app.request_types[1] = "normal"
        app.control_queue.put_nowait(("complete", 1, "final", [], (None, None), "normal"))
        # Llega después de encolar el complete pero antes de procesarlo:
        # _flush_pending_chunks debe recogerlo dentro de finish().
        app.chunks.append(1, "cola-del-stream")

        app.process_ui_events()

        pintado = "".join(llamada[0][1] for llamada in app.stream_chunk.call_args_list)
        self.assertIn("cola-del-stream", pintado)

    def test_los_chunks_de_una_peticion_cancelada_se_descartan(self):
        app = _app_sin_ventana()
        app.chunks.append(99, "de una petición ya cancelada")

        app.process_ui_events()

        app.stream_chunk.assert_not_called()
        self.assertEqual(app.chunks.pending_requests(), 0, "No deben acumularse indefinidamente")


class TestFlujoCompletoConProveedorEnRafaga(unittest.TestCase):
    """Extremo a extremo: LLMSessionManager real publicando en los canales reales."""

    def test_una_respuesta_larga_llega_entera_y_cierra_la_peticion(self):
        app = _app_sin_ventana()
        request_id = 1
        app.request_types[request_id] = "normal"
        piezas = [f"palabra{i} " for i in range(3000)]

        def stream_en_rafaga(self, profile, api_key, prompt, rid=None, cancel_event=None):
            for pieza in piezas:
                yield StreamChunk(pieza)
            yield StreamChunk("", 100, 50)

        profile = LlmProfile(
            provider="openai_compatible",
            endpoint="https://api.example.com/v1/chat/completions",
            model="m",
        )
        manager = LLMSessionManager()
        with patch.object(LLMClient, "stream", stream_en_rafaga):
            hilo = threading.Thread(target=lambda: manager.stream_response(
                profile, "clave", "articulo", "paquete", [],
                on_chunk=lambda c: app.chunks.append(request_id, c),
                on_error=lambda e: app.control_queue.put_nowait(
                    ("error", request_id, e, [])),
                on_complete=lambda r, u: app.control_queue.put_nowait(
                    ("complete", request_id, r, [], u, "normal")),
                request_id=request_id,
            ))
            hilo.start()
            hilo.join(timeout=30)

        self.assertFalse(hilo.is_alive(), "El worker no debe quedar bloqueado publicando")

        app.process_ui_events()

        pintado = "".join(llamada[0][1] for llamada in app.stream_chunk.call_args_list)
        self.assertEqual(pintado, "".join(piezas), "El texto pintado debe ser el recibido")
        self.assertNotIn(request_id, app.request_types, "La petición debe quedar cerrada")
        self.assertEqual(
            [m.content for m in app.docs.session.conversation], ["".join(piezas)]
        )

    def test_un_error_a_mitad_de_rafaga_conserva_lo_recibido(self):
        from articulador_core.llm import LlmError

        app = _app_sin_ventana()
        request_id = 2
        app.request_types[request_id] = "normal"
        app._append_notice = Mock()
        piezas = [f"p{i} " for i in range(500)]

        def stream_que_falla(self, profile, api_key, prompt, rid=None, cancel_event=None):
            for pieza in piezas:
                yield StreamChunk(pieza)
            raise LlmError("El proveedor cortó la conexión.")

        profile = LlmProfile(
            provider="openai_compatible",
            endpoint="https://api.example.com/v1/chat/completions",
            model="m",
        )
        manager = LLMSessionManager()
        with patch.object(LLMClient, "stream", stream_que_falla):
            hilo = threading.Thread(target=lambda: manager.stream_response(
                profile, "clave", "articulo", "paquete", [],
                on_chunk=lambda c: app.chunks.append(request_id, c),
                on_error=lambda e: app.control_queue.put_nowait(
                    ("error", request_id, f"No pude responder: {e}", [])),
                on_complete=lambda r, u: app.control_queue.put_nowait(
                    ("complete", request_id, r, [], u, "normal")),
                request_id=request_id,
            ))
            hilo.start()
            hilo.join(timeout=30)

        self.assertFalse(hilo.is_alive())

        app.process_ui_events()

        pintado = "".join(llamada[0][1] for llamada in app.stream_chunk.call_args_list)
        self.assertEqual(pintado, "".join(piezas), "La salida parcial no puede perderse")
        app._append_notice.assert_called_once()
        self.assertIn("[INCOMPLETO]", app._append_notice.call_args[0][0])
        self.assertNotIn(request_id, app.request_types)


if __name__ == "__main__":
    unittest.main()
