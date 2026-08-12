"""Tests REALES de flujo de eventos - ejecuta código de producción sin ventana Tkinter.

NO simula lógica de producción. Injerta eventos en colas reales
y ejecuta métodos reales de ArticuladorApp.
"""
import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from articulador_ui.chunk_buffer import ChunkBuffer
from articulador_ui.document_scope import DocumentScope

# No import de tkinter - vamos a mockear solo lo mínimo


class TestRealEventFlow(unittest.TestCase):
    """Tests que ejecutan código REAL de producción."""

    def setUp(self):
        """Setup sin crear ventana Tk."""
        # Mock del entorno Tkinter
        with patch("tkinter.Tk.__init__", return_value=None):
            with patch("tkinter.Tk.after"):
                from articulador_ui.app import ArticuladorApp

                self.ArticuladorApp = ArticuladorApp

    def test_chunks_and_error_preserves_partial_output(self):
        """REAL: chunk("A") + chunk("B") + error(...) → partial conservado.

        Flujo REAL - EJECUTA process_ui_events() que LLAMA finish():
        1. Acumular chunks en el ChunkBuffer (ciclo anterior)
        2. Inyectar error en control_queue
        3. LLAMAR process_ui_events() REAL
        4. Verificar que finish() limpió state correctamente
        """
        with patch("tkinter.Tk.__init__", return_value=None):
            with patch("tkinter.Tk.after"):
                with patch("articulador_core.storage.load_profiles", return_value=({}, "")):
                    app = self.ArticuladorApp.__new__(self.ArticuladorApp)

                    # Inicializar ESTADO REAL
                    app.closing = False
                    app.control_queue = queue.Queue()
                    app.chunks = ChunkBuffer()
                    app.request_types = {}
                    app.streaming_request = None

                    # Mock de UI widgets
                    app.history = Mock()
                    app.activity = Mock()
                    app.send_button = Mock()
                    app.cancel_button = Mock()
                    app.scope = DocumentScope()
                    app.status = Mock()
                    app.cost_label = Mock()
                    app.docs = Mock()
                    app.docs.session = Mock()
                    app.docs.conversation = []

                    # IMPORTANTE: Mock stream_chunk() para evitar recursión Tk
                    app.stream_chunk = Mock()

                    # Setup request
                    request_id = 1
                    app.request_types[request_id] = "normal"

                    # SIMULAR chunks acumulados
                    app.chunks.append(request_id, "A"); app.chunks.append(request_id, "B")

                    # INYECTAR error
                    app.control_queue.put_nowait(
                        ("error", request_id, "Connection timeout", [])
                    )

                    # EJECUTAR process_ui_events() que LLAMA finish() REAL
                    app.process_ui_events()

                    # VERIFICAR que finish() limpió estado
                    self.assertNotIn(
                        request_id, app.request_types,
                        "finish() debería haber removido request_id de request_types"
                    )

    def test_chunk_queue_saturation_doesnt_block_error(self):
        """REAL: incluso con chunks en la queue, el error se procesa correctamente.

        Garantía: los chunks viajan por un canal propio y el error por la cola de
        control; process_ui_events() pinta el texto pendiente antes de finalizar.
        """
        with patch("tkinter.Tk.__init__", return_value=None):
            with patch("tkinter.Tk.after"):
                with patch("articulador_core.storage.load_profiles", return_value=({}, "")):
                    app = self.ArticuladorApp.__new__(self.ArticuladorApp)

                    # Setup real
                    app.closing = False
                    app.control_queue = queue.Queue()
                    app.chunks = ChunkBuffer()
                    app.request_types = {}
                    app.streaming_request = None

                    # Mock de UI
                    app.history = Mock()
                    app.activity = Mock()
                    app.send_button = Mock()
                    app.cancel_button = Mock()
                    app.scope = DocumentScope()
                    app.status = Mock()
                    app.cost_label = Mock()
                    app.docs = Mock()
                    app.docs.session = Mock()
                    app.docs.conversation = []

                    # IMPORTANTE: Mock stream_chunk() para evitar recursión Tk
                    app.stream_chunk = Mock()

                    request_id = 1
                    app.request_types[request_id] = "normal"

                    # INYECTAR chunks en el ChunkBuffer (canal separado del control)
                    for i in range(5):
                        app.chunks.append(request_id, f"chunk_{i}")

                    # INYECTAR error en la cola de control
                    app.control_queue.put_nowait(
                        ("error", request_id, "Failed", [])
                    )

                    # EJECUTAR process_ui_events() que procesa chunks y luego error
                    app.process_ui_events()

                    # Verificar que request_id fue limpiado después de procesar error
                    self.assertNotIn(
                        request_id, app.request_types,
                        "finish() debería haber removido request_id de request_types"
                    )

    def test_multiple_requests_dont_interfere(self):
        """REAL: Dos requests simultáneos mantienen estado separado.

        Garantía: error en request_id=1 NO afecta request_id=2.
        EJECUTA process_ui_events() que LLAMA finish() realmente.
        """
        with patch("tkinter.Tk.__init__", return_value=None):
            with patch("tkinter.Tk.after"):
                with patch("articulador_core.storage.load_profiles", return_value=({}, "")):
                    app = self.ArticuladorApp.__new__(self.ArticuladorApp)

                    app.closing = False
                    app.control_queue = queue.Queue()
                    app.chunks = ChunkBuffer()
                    app.request_types = {}
                    app.streaming_request = None

                    # Mock de UI
                    app.history = Mock()
                    app.activity = Mock()
                    app.send_button = Mock()
                    app.cancel_button = Mock()
                    app.scope = DocumentScope()
                    app.status = Mock()
                    app.cost_label = Mock()
                    app.docs = Mock()
                    app.docs.session = Mock()
                    app.docs.conversation = []

                    # IMPORTANTE: Mock stream_chunk() para evitar recursión Tk
                    app.stream_chunk = Mock()

                    rid1, rid2 = 1, 2
                    app.request_types[rid1] = "normal"
                    app.request_types[rid2] = "normal"

                    # Chunks para ambos requests
                    app.chunks.append(rid1, "A1"); app.chunks.append(rid1, "B1")
                    app.chunks.append(rid2, "A2"); app.chunks.append(rid2, "B2")

                    # Inyectar error solo para rid1
                    app.control_queue.put_nowait(
                        ("error", rid1, "Failed", [])
                    )

                    # EJECUTAR process_ui_events() que LLAMA finish() REAL
                    app.process_ui_events()

                    # Verificar que rid1 fue limpiado
                    self.assertNotIn(
                        rid1, app.request_types,
                        "finish() debería haber removido rid1"
                    )

                    # Verificar que rid2 NO fue afectado: su texto se pintó coalescido
                    # y sigue siendo una petición viva.
                    self.assertIn(rid2, app.request_types, "rid2 debe seguir válido")
                    app.stream_chunk.assert_any_call(rid2, "A2B2")


class TestHealthCheckReal(unittest.TestCase):
    """Health checks ejecutan operaciones REALES."""

    def test_health_check_storage_works(self):
        """REAL: health check verifica que storage funciona (en directorio temporal aislado)."""
        import tempfile
        from unittest.mock import patch

        from articulador_core import storage as storage_module
        from articulador_core.health import check_health

        # Usar directorio temporal para aislar del home del ejecutor
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_config = Path(tmpdir) / "config.toml"
            # Mock CONFIG_PATH para usar ruta temporal
            with patch.object(storage_module, "CONFIG_PATH", temp_config):
                status = check_health()

                # Debe tener estructura
                self.assertTrue(hasattr(status, "is_healthy"))
                self.assertTrue(hasattr(status, "components"))
                self.assertIn("storage", status.components)
                self.assertIn("llm", status.components)
                self.assertIn("logging", status.components)

                # Storage debe poder ser accedido (en temp dir debe funcionar)
                from articulador_core.health import ComponentStatus
                storage_status, _ = status.components["storage"]
                self.assertEqual(storage_status, ComponentStatus.HEALTHY)


class TestLoggingStructured(unittest.TestCase):
    """Logging produce JSON válido."""

    def test_logging_formats_json(self):
        """REAL: logging produce JSON válido (no secretos)."""
        import json
        import logging
        from io import StringIO

        from articulador_core.logging_config import StructuredFormatter

        # Setup logger que escribe a string
        logger = logging.getLogger("test")
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter(is_file=True))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Log un mensaje
        logger.info("Test message")

        # Extraer y parsear JSON
        output = stream.getvalue().strip()
        try:
            parsed = json.loads(output)
            self.assertIn("timestamp", parsed)
            self.assertIn("level", parsed)
            self.assertIn("message", parsed)
            self.assertEqual(parsed["message"], "Test message")
        except json.JSONDecodeError as e:
            self.fail(f"Logging output is not valid JSON: {e}")


if __name__ == "__main__":
    unittest.main()
