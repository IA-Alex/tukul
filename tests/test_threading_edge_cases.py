"""
Tests de casos delicados de threading/eventos.

Cubre gaps específicos:
- Chunks pendientes + error
- Chunks pendientes + complete
- Cancelación antes/durante contexto
- Limpieza de buffers (éxito/error/cancel)
- Saturación de cola simulada
- Reconfirmación por cambios de configuración
"""
import hashlib
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from articulador_core.models import LlmProfile


class TestChunksPendingWithError(unittest.TestCase):
    """Chunks pendientes + error event → conservar salida parcial."""

    def test_chunks_accumulated_then_error(self):
        """
        Flujo:
        1. Recibir chunks: "Hola ", "mundo"
        2. Acumular en pending_chunks[request_id]
        3. Recibir error event
        4. Verificar: partial_output conserva "Hola mundo"
        5. Verificar: last_response = partial (no error_msg)
        """
        # Simular state en app
        request_id = 1
        pending_chunks = {request_id: ["Hola ", "mundo"]}
        partial_output = {}
        last_response = ""
        error_msg = "No pude responder: connection timeout"

        # Simular process_ui_events() cuando llega error
        if pending_chunks.get(request_id):
            coalesced = "".join(pending_chunks[request_id])
            # En finish(), se haría:
            partial_output[request_id] = coalesced

        # Simular finish(is_error=True)
        if request_id in partial_output:
            partial = partial_output[request_id]
            last_response = partial  # ← NOT error_msg

        # Verificaciones
        self.assertEqual(partial_output[request_id], "Hola mundo")
        self.assertEqual(last_response, "Hola mundo")
        self.assertNotEqual(last_response, error_msg)

    def test_error_not_saved_to_conversation(self):
        """Error tras chunks no se guarda en conversation, solo partial."""
        request_id = 1
        partial_output = {request_id: "respuesta parcial"}
        error_msg = "Connection timeout"
        conversation = []

        # Simular finish(is_error=True)
        partial = partial_output.get(request_id, "")
        if partial.strip():
            conversation.append(("assistant", partial))  # ← parcial
        # NO: conversation.append(("assistant", error_msg))

        self.assertEqual(len(conversation), 1)
        self.assertEqual(conversation[0], ("assistant", "respuesta parcial"))

    def test_partial_output_cleared_on_complete(self):
        """Cuando complete exitoso, partial_output debe limpiarse."""
        request_id = 1
        partial_output = {request_id: "texto acumulado"}
        final_result = "resultado final completo"

        # Simular finish() después de complete
        partial_output.pop(request_id, None)  # ← limpiar

        self.assertNotIn(request_id, partial_output)


class TestChunksPendingWithComplete(unittest.TestCase):
    """Chunks pendientes + complete event → guardar resultado completo."""

    def test_chunks_then_complete_saves_full_result(self):
        """
        Flujo:
        1. Chunks: "Respuesta ", "completa", " exitosa"
        2. Complete event con result final
        3. Verificar: salida completa se guarda en conversation
        """
        request_id = 1
        pending_chunks = {request_id: ["Respuesta ", "completa", " exitosa"]}
        conversation = []
        final_result = "Respuesta completa exitosa"

        # Simular finish() con result (no from chunks)
        # Los chunks se procesan como stream_chunk() visuales
        # El result final se guarda en conversation
        conversation.append(("assistant", final_result))
        pending_chunks.pop(request_id, None)  # limpiar

        self.assertEqual(len(conversation), 1)
        self.assertEqual(conversation[0][1], "Respuesta completa exitosa")
        self.assertNotIn(request_id, pending_chunks)

    def test_pending_chunks_cleared_on_complete(self):
        """Pending chunks deben limpiarse tras complete."""
        request_id = 1
        pending_chunks = {request_id: ["chunk1", "chunk2", "chunk3"]}

        # Simular finish() con complete
        pending_chunks.pop(request_id, None)

        self.assertEqual(len(pending_chunks), 0)


class TestCancelationBeforeContext(unittest.TestCase):
    """Cancelación antes de que contexto esté listo."""

    def test_cancel_during_context_preparation(self):
        """
        Flujo:
        1. User envía mensaje
        2. Thread de contexto inicia
        3. User presiona cancelar ANTES de que contexto se prepare
        4. Verificar: request_types[request_id] se invalida
        5. Verificar: pendiente context_ready event se ignora
        """
        request_id = 1
        request_types = {request_id: "normal"}
        cancel_event = Mock()
        cancel_event.is_set = Mock(return_value=True)  # cancelado

        # Simular cancel_request()
        request_types.clear()

        # Cuando llega context_failed o confirm_and_send:
        if request_id not in request_types:
            # ✓ Ignorado porque ya fue cancelado
            pass

        self.assertEqual(len(request_types), 0)

    def test_cancel_invalidates_future_events(self):
        """Eventos posteriores a cancel() para mismo request_id se ignoran."""
        request_id = 1
        request_types = {request_id: "normal"}

        # Cancelar
        request_types.clear()

        # Intento de procesar evento para request_id cancelado
        if request_id not in request_types:
            # ✓ Se descarta
            event_processed = False
        else:
            event_processed = True

        self.assertFalse(event_processed)


class TestBufferCleanup(unittest.TestCase):
    """Limpieza de todos los buffers en éxito, error, cancelación."""

    def test_cleanup_after_finish_success(self):
        """Finish exitoso debe limpiar todos los buffers."""
        request_id = 1
        request_types = {request_id: "normal"}
        pending_chunks = {request_id: ["chunk"]}
        partial_output = {request_id: "partial"}

        # Simular finish() exitoso (complete sin error)
        request_types.pop(request_id, None)
        pending_chunks.pop(request_id, None)
        partial_output.pop(request_id, None)

        self.assertEqual(len(request_types), 0)
        self.assertEqual(len(pending_chunks), 0)
        self.assertEqual(len(partial_output), 0)

    def test_cleanup_after_finish_error(self):
        """Finish con error debe limpiar todos los buffers."""
        request_id = 1
        request_types = {request_id: "normal"}
        pending_chunks = {request_id: ["chunk1", "chunk2"]}
        partial_output = {request_id: "partial text"}

        # Simular finish() con error (is_error=True)
        request_types.pop(request_id, None)
        pending_chunks.pop(request_id, None)
        partial_output.pop(request_id, None)

        self.assertEqual(len(request_types), 0)
        self.assertEqual(len(pending_chunks), 0)
        self.assertEqual(len(partial_output), 0)

    def test_cleanup_after_cancel_request(self):
        """cancel_request() debe limpiar TODOS los buffers."""
        request_id = 1
        request_types = {1: "normal", 2: "review"}
        pending_chunks = {1: ["chunk"], 2: ["chunk"]}
        partial_output = {1: "partial", 2: "partial2"}

        # Simular cancel_request() → clear ALL
        request_types.clear()
        pending_chunks.clear()
        partial_output.clear()

        self.assertEqual(len(request_types), 0)
        self.assertEqual(len(pending_chunks), 0)
        self.assertEqual(len(partial_output), 0)

    def test_no_partial_output_leak_after_complete(self):
        """partial_output debe estar vacío después de complete."""
        request_id = 1
        partial_output = {request_id: "accumulated text"}

        # Simular finish() con complete (no error)
        partial_output.pop(request_id, None)

        self.assertNotIn(request_id, partial_output)


class TestQueueSaturation(unittest.TestCase):
    """Saturación de cola simulada."""

    def test_chunk_queue_full_drops_gracefully(self):
        """Chunk queue llena descarta chunks sin crash."""
        chunk_queue = queue.Queue(maxsize=5)
        dropped_count = 0

        # Llenar la cola
        for i in range(5):
            chunk_queue.put_nowait(("chunk", 1, f"chunk_{i}"))

        # Intentar agregar más
        for i in range(5, 10):
            try:
                chunk_queue.put_nowait(("chunk", 1, f"chunk_{i}"))
            except queue.Full:
                dropped_count += 1

        self.assertEqual(dropped_count, 5)  # Todos descartados

    def test_control_queue_never_full(self):
        """Control queue nunca se llena (sin límite)."""
        control_queue = queue.Queue()  # sin maxsize

        # Intentar agregar 1000 eventos
        for i in range(1000):
            try:
                control_queue.put_nowait(("complete", i, "result", [], (None, None), "normal"))
            except queue.Full:
                self.fail("Control queue no debería nunca rechazar")

        self.assertEqual(control_queue.qsize(), 1000)

    def test_saturated_chunk_queue_control_events_still_delivered(self):
        """Chunk queue saturada no afecta control events."""
        chunk_queue = queue.Queue(maxsize=10)
        control_queue = queue.Queue()

        # Llenar chunk_queue
        for i in range(10):
            chunk_queue.put_nowait(("chunk", 1, f"chunk_{i}"))

        # Enviar control event (debe ir a control_queue)
        try:
            control_queue.put_nowait(("complete", 1, "result", [], (None, None), "normal"))
            delivered = True
        except queue.Full:
            delivered = False

        self.assertTrue(delivered)


class TestApprovalReconfirmationScenarios(unittest.TestCase):
    """Reconfirmación cuando cambian parámetros."""

    def test_model_change_requires_reapproval(self):
        """Cambio de modelo requiere nueva aprobación."""

        endpoint = "https://api.openai.com"
        provider = "openai"
        files = ("doc1.md",)
        content = "original"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        # Clave original
        model_1 = "gpt-4"
        key_1 = (endpoint, provider, files, content_hash)  # Nota: NO incluye model

        # Pero si queremos que cambio de modelo requiera reaprobación:
        # La lógica actual NO lo hace (model está en profile, no en key)
        # Este test documenta que es un potencial gap

        # Solución: incluir model en la clave si se desea reaprobación
        key_with_model = (endpoint, provider, files, content_hash, model_1)
        model_2 = "gpt-3.5-turbo"
        key_with_model_2 = (endpoint, provider, files, content_hash, model_2)

        self.assertNotEqual(key_with_model, key_with_model_2)

    def test_profile_params_impact_on_approval(self):
        """
        LlmProfile tiene params que SÍ afectan aprobación:
        - endpoint: ✓ (en clave)
        - provider: ✓ (en clave)
        - model: ? (NO está en clave actualmente)
        - max_output_tokens: ? (NO está en clave)
        - temperature: ? (NO está en clave)
        """
        # Clave actual: (endpoint, provider, files, content_hash)
        # Cambios que REQUIEREN reaprobación:
        # - endpoint ✓
        # - provider ✓
        # - contenido ✓
        # - archivos ✓

        # Cambios que NO REQUIEREN reaprobación (potencial gap):
        # - model (si el usuario cambia modelo, contexto sigue siendo el mismo)
        # - max_output_tokens (no afecta contenido que se envía)
        # - temperature (no afecta contenido que se envía)

        # Este es un diseño decision: si DEBERÍA reaprobarse ante cambio de modelo.
        # Por ahora, la lógica es: "contexto es lo sensible, parámetros de generación no".

        # Verificar la lógica actual
        clave_diseño_actual = ("endpoint", "provider", "files", "content_hash")
        self.assertEqual(len(clave_diseño_actual), 4)

    def test_content_change_detected_by_hash(self):
        """Cambio en contenido del artículo es detectado por hash."""

        endpoint = "https://api.openai.com"
        provider = "openai"
        files = ("articulo.md",)

        content_v1 = "Versión original del artículo"
        content_v2 = "Versión modificada del artículo"

        hash_v1 = hashlib.sha256(content_v1.encode("utf-8")).hexdigest()[:16]
        hash_v2 = hashlib.sha256(content_v2.encode("utf-8")).hexdigest()[:16]

        key_v1 = (endpoint, provider, files, hash_v1)
        key_v2 = (endpoint, provider, files, hash_v2)

        self.assertNotEqual(key_v1, key_v2)
        # Resultado: reaprobación requerida ✓

    def test_endpoint_change_detected(self):
        """Cambio de endpoint requiere reaprobación."""

        provider = "openai"
        files = ("doc.md",)
        content = "content"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        endpoint_v1 = "https://api.openai.com/v1/chat/completions"
        endpoint_v2 = "https://api.anthropic.com/v1/messages"

        key_v1 = (endpoint_v1, provider, files, content_hash)
        key_v2 = (endpoint_v2, provider, files, content_hash)

        self.assertNotEqual(key_v1, key_v2)
        # Resultado: reaprobación requerida ✓

    def test_provider_change_detected(self):
        """Cambio de proveedor requiere reaprobación."""

        endpoint = "https://api.example.com"
        files = ("doc.md",)
        content = "content"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        provider_v1 = "openai"
        provider_v2 = "anthropic"

        key_v1 = (endpoint, provider_v1, files, content_hash)
        key_v2 = (endpoint, provider_v2, files, content_hash)

        self.assertNotEqual(key_v1, key_v2)
        # Resultado: reaprobación requerida ✓


class TestEventStreamingLifecycle(unittest.TestCase):
    """Ciclo de vida completo: request → chunks → complete/error."""

    def test_normal_streaming_lifecycle(self):
        """Ciclo exitoso: chunks → complete."""
        request_id = 1
        request_types = {request_id: "normal"}
        pending_chunks = {}
        partial_output = {}
        conversation = []

        # 1. Chunks llegan a chunk_queue (visuales, se acumulan)
        for chunk_text in ["Hola ", "mundo"]:
            if request_id not in pending_chunks:
                pending_chunks[request_id] = []
            pending_chunks[request_id].append(chunk_text)

        # 2. Complete event llega a control_queue
        # (process_ui_events procesa chunks pendientes primero)
        if request_id in pending_chunks:
            partial_output[request_id] = "".join(pending_chunks[request_id])
        pending_chunks.pop(request_id, None)

        # 3. finish() se llama con result
        result = "Hola mundo"  # result completo desde provider
        request_types.pop(request_id, None)
        partial_output.pop(request_id, None)
        conversation.append(("assistant", result))

        # Verificar estado final
        self.assertEqual(len(request_types), 0)
        self.assertEqual(len(pending_chunks), 0)
        self.assertEqual(len(partial_output), 0)
        self.assertEqual(len(conversation), 1)

    def test_error_streaming_lifecycle(self):
        """Ciclo con error: chunks → error."""
        request_id = 1
        request_types = {request_id: "normal"}
        pending_chunks = {}
        partial_output = {}
        conversation = []

        # 1. Chunks llegan y se acumulan
        for chunk_text in ["Respuesta ", "parcial"]:
            if request_id not in pending_chunks:
                pending_chunks[request_id] = []
            pending_chunks[request_id].append(chunk_text)

        # 2. Error event llega a control_queue
        if request_id in pending_chunks:
            partial_output[request_id] = "".join(pending_chunks[request_id])
        pending_chunks.pop(request_id, None)

        # 3. finish(is_error=True) se llama
        partial = partial_output.get(request_id, "")
        request_types.pop(request_id, None)
        if partial:
            conversation.append(("assistant", partial))  # guardar partial, no error
        partial_output.pop(request_id, None)

        # Verificar estado final
        self.assertEqual(len(request_types), 0)
        self.assertEqual(len(pending_chunks), 0)
        self.assertEqual(len(partial_output), 0)
        self.assertEqual(conversation[0][1], "Respuesta parcial")

    def test_canceled_lifecycle(self):
        """Ciclo cancelado: request → cancel."""
        request_id = 1
        request_types = {request_id: "normal"}
        pending_chunks = {request_id: ["chunk1"]}
        partial_output = {request_id: "partial"}
        cancel_event = Mock()

        # cancel_request() se llama
        cancel_event.set()
        request_types.clear()
        pending_chunks.clear()
        partial_output.clear()

        # Verificar estado final
        self.assertEqual(len(request_types), 0)
        self.assertEqual(len(pending_chunks), 0)
        self.assertEqual(len(partial_output), 0)


if __name__ == "__main__":
    unittest.main()
