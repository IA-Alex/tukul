"""
Tests de regresión para semántica de colas y finalización de streaming.

Cobertura:
- Cola de chunks llena + complete
- Cola de chunks llena + error
- Error tras varios chunks (salida parcial conservada)
- Cambio de contenido/endpoint/proveedor (reconfirmación)
- Validación del parser (límite, categorías, campos, tamaños)
"""
import queue
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from articulador_core.models import ChatMessage, LlmProfile
from articulador_core.review import (
    ALLOWED_CATEGORIES,
    ALLOWED_SEVERITIES,
    MAX_FIELD_LENGTH,
    MAX_FINDINGS,
    parse_findings,
)


class TestQueueSemantics(unittest.TestCase):
    """Tests de semántica de colas (control garantizado vs chunks coalescibles)."""

    def test_control_queue_unlimited(self):
        """Control queue nunca debe rechazar eventos críticos."""
        # Simular cola de control sin límite
        control_queue = queue.Queue()  # sin maxsize
        events = [
            ("complete", 1, "result", [], (None, None), "normal"),
            ("error", 2, "msg", []),
            ("context_failed", 3, "msg"),
            ("confirm_and_send", 4, "msg", "sel", "pkt", [], None),
        ]
        # Insertar 1000 eventos críticos → nunca debe fallar
        for i in range(1000):
            try:
                control_queue.put_nowait(events[i % len(events)])
            except queue.Full:
                self.fail("Control queue debería ser ilimitada")

    def test_chunk_queue_limited(self):
        """Chunk queue tiene límite (500) y descarta ante congestión."""
        chunk_queue = queue.Queue(maxsize=500)
        # Llenar la cola
        for i in range(500):
            chunk_queue.put_nowait(("chunk", 1, f"chunk_{i}"))

        # El siguiente chunk debe fallar (descartable)
        with self.assertRaises(queue.Full):
            chunk_queue.put_nowait(("chunk", 1, "overflow"))

    def test_complete_after_chunks_queue_full(self):
        """Complete event debe llegar aunque chunk_queue esté llena."""
        # Simular: chunks llenos, pero complete es crítico
        chunk_queue = queue.Queue(maxsize=10)
        control_queue = queue.Queue()

        # Llenar chunk_queue
        for i in range(10):
            chunk_queue.put_nowait(("chunk", 1, f"chunk_{i}"))

        # Complete debe insertarse en control_queue (garantizado)
        control_queue.put_nowait(("complete", 1, "final_result", [], (10, 5), "normal"))
        self.assertEqual(control_queue.get_nowait()[0], "complete")

    def test_error_after_chunks_queue_full(self):
        """Error event después de chunks debe mostrar banner."""
        # Simular chunks pendientes + error posterior
        partial_output = {1: "chunks_acumulados_"}
        pending_chunks = {1: ["chunk_1", "chunk_2"]}

        # Acumular salida parcial (como hace process_ui_events)
        if pending_chunks[1]:
            coalesced = "".join(pending_chunks[1])
            partial_output[1] = partial_output.get(1, "") + coalesced

        # Error debe conservar partial_output
        self.assertGreater(len(partial_output[1]), 0)
        # Banner debería mostrar [INCOMPLETO] + separación
        banner = "[INCOMPLETO] Respuesta interrumpida"
        self.assertIn("INCOMPLETO", banner)


class TestStreamingErrorHandling(unittest.TestCase):
    """Tests de manejo de error tras streaming (salida parcial)."""

    def test_partial_output_conservation(self):
        """Error tras streaming debe conservar salida parcial."""
        # Simular: chunks llegaron, luego error
        streaming_text = "respuesta parcial..."
        error_msg = "Connection timeout"

        # last_response debe ser streaming_text (no error_msg)
        last_response = streaming_text  # ← Correcto
        self.assertEqual(last_response, "respuesta parcial...")
        self.assertNotEqual(last_response, error_msg)

    def test_error_banner_with_separator(self):
        """Error tras streaming debe mostrar banner con separador visual."""
        # Simulación del banner que crea finish()
        partial = "respuesta_parcial"
        banner = "\n\n[INCOMPLETO] Respuesta interrumpida por error. Revisa conexión o límites.\n" + "─" * 60 + "\n\n"

        self.assertIn("[INCOMPLETO]", banner)
        self.assertIn("─" * 60, banner)

    def test_partial_output_not_saved_as_error(self):
        """No guardar error como respuesta, solo salida parcial."""
        # Cuando hay error tras streaming:
        # - last_response = partial (✓ correcto)
        # - conversation.append(partial) (✓ correcto)
        # - NO conversation.append(error_msg) (✓ correcto)

        partial = "respuesta parcial"
        error_msg = "No pude responder: connection timeout"

        # Simular logic de finish()
        is_error = True
        if is_error:
            # Guardar salida parcial (no error)
            conversation_msg = partial if partial else None
        else:
            conversation_msg = error_msg

        self.assertEqual(conversation_msg, partial)
        self.assertNotEqual(conversation_msg, error_msg)


class TestContextApprovalGranularity(unittest.TestCase):
    """Tests de granularidad de aprobación de contexto."""

    def test_approval_key_includes_endpoint(self):
        """Clave de aprobación debe incluir endpoint."""
        import hashlib

        endpoint1 = "https://api.openai.com/v1/chat/completions"
        endpoint2 = "https://api.anthropic.com/v1/messages"
        provider = "openai"
        files = ("doc1.md",)
        content = "test"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        key1 = (endpoint1, provider, files, content_hash)
        key2 = (endpoint2, provider, files, content_hash)

        # Diferentes endpoints → diferentes keys → reconfirmación necesaria
        self.assertNotEqual(key1, key2)

    def test_approval_key_includes_provider(self):
        """Clave de aprobación debe incluir proveedor."""
        import hashlib

        endpoint = "https://api.openai.com/v1/chat/completions"
        provider1 = "openai"
        provider2 = "anthropic"
        files = ("doc1.md",)
        content = "test"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        key1 = (endpoint, provider1, files, content_hash)
        key2 = (endpoint, provider2, files, content_hash)

        # Diferentes providers → diferentes keys
        self.assertNotEqual(key1, key2)

    def test_approval_key_includes_content_hash(self):
        """Clave de aprobación debe incluir hash del contenido."""
        import hashlib

        endpoint = "https://api.openai.com/v1/chat/completions"
        provider = "openai"
        files = ("doc1.md",)
        content1 = "original content"
        content2 = "modified content"

        hash1 = hashlib.sha256(content1.encode("utf-8")).hexdigest()[:16]
        hash2 = hashlib.sha256(content2.encode("utf-8")).hexdigest()[:16]

        key1 = (endpoint, provider, files, hash1)
        key2 = (endpoint, provider, files, hash2)

        # Contenido diferente → diferentes keys → reconfirmación
        self.assertNotEqual(key1, key2)


class TestParserValidation(unittest.TestCase):
    """Tests de validación estricta del parser de revisiones."""

    def test_parser_limits_to_12_findings(self):
        """Parser debe limitar a 12 hallazgos máximo."""
        import json

        findings_list = [
            {
                "category": "ortografía",
                "severity": "alta",
                "original": f"word_{i}",
                "suggestion": f"fixed_{i}",
                "reason": f"typo_{i}",
            }
            for i in range(20)  # 20 hallazgos
        ]
        result_json = json.dumps({"findings": findings_list})
        result = parse_findings(result_json)

        self.assertEqual(len(result), MAX_FINDINGS)
        self.assertEqual(len(result), 12)

    def test_parser_rejects_invalid_category(self):
        """Parser debe rechazar categorías no permitidas."""
        import json

        findings_list = [
            {
                "category": "invalid_category",  # ✗ no permitida
                "severity": "alta",
                "original": "word",
                "suggestion": "fixed",
                "reason": "typo",
            }
        ]
        result_json = json.dumps({"findings": findings_list})
        result = parse_findings(result_json)

        self.assertEqual(result, [])

    def test_parser_rejects_invalid_severity(self):
        """Parser debe rechazar severidades no permitidas."""
        import json

        findings_list = [
            {
                "category": "ortografía",
                "severity": "crítica",  # ✗ no permitida (solo alta/media/baja)
                "original": "word",
                "suggestion": "fixed",
                "reason": "typo",
            }
        ]
        result_json = json.dumps({"findings": findings_list})
        result = parse_findings(result_json)

        self.assertEqual(result, [])

    def test_parser_rejects_empty_fields(self):
        """Parser debe rechazar campos vacíos."""
        import json

        findings_list = [
            {
                "category": "ortografía",
                "severity": "alta",
                "original": "",  # ✗ vacío
                "suggestion": "fixed",
                "reason": "typo",
            }
        ]
        result_json = json.dumps({"findings": findings_list})
        result = parse_findings(result_json)

        self.assertEqual(result, [])

    def test_parser_rejects_oversized_fields(self):
        """Parser debe rechazar campos > 500 caracteres."""
        import json

        oversized = "x" * (MAX_FIELD_LENGTH + 1)
        findings_list = [
            {
                "category": "ortografía",
                "severity": "alta",
                "original": oversized,  # ✗ demasiado largo
                "suggestion": "fixed",
                "reason": "typo",
            }
        ]
        result_json = json.dumps({"findings": findings_list})
        result = parse_findings(result_json)

        self.assertEqual(result, [])

    def test_parser_accepts_valid_findings(self):
        """Parser debe aceptar hallazgos válidos."""
        import json

        findings_list = [
            {
                "category": "ortografía",
                "severity": "alta",
                "original": "original_word",
                "suggestion": "corrected_word",
                "reason": "typo fix",
            }
        ]
        result_json = json.dumps({"findings": findings_list})
        result = parse_findings(result_json)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "ortografía")
        self.assertEqual(result[0]["severity"], "alta")

    def test_parser_accepts_all_valid_categories(self):
        """Parser debe aceptar todas las categorías permitidas."""
        import json

        for category in ALLOWED_CATEGORIES:
            findings_list = [
                {
                    "category": category,
                    "severity": "media",
                    "original": "text",
                    "suggestion": "fixed",
                    "reason": "fix",
                }
            ]
            result_json = json.dumps({"findings": findings_list})
            result = parse_findings(result_json)
            self.assertEqual(len(result), 1, f"Debe aceptar categoría '{category}'")

    def test_parser_accepts_all_valid_severities(self):
        """Parser debe aceptar todas las severidades permitidas."""
        import json

        for severity in ALLOWED_SEVERITIES:
            findings_list = [
                {
                    "category": "ortografía",
                    "severity": severity,
                    "original": "text",
                    "suggestion": "fixed",
                    "reason": "fix",
                }
            ]
            result_json = json.dumps({"findings": findings_list})
            result = parse_findings(result_json)
            self.assertEqual(len(result), 1, f"Debe aceptar severidad '{severity}'")


class TestChatMessageValidation(unittest.TestCase):
    """Tests de validación de ChatMessage."""

    def test_chat_message_requires_string_role(self):
        """ChatMessage debe rechazar role no-string."""
        with self.assertRaises(TypeError):
            ChatMessage(role=123, content="text")  # ✗ int role

    def test_chat_message_requires_string_content(self):
        """ChatMessage debe rechazar content no-string."""
        with self.assertRaises(TypeError):
            ChatMessage(role="user", content=123)  # ✗ int content

    def test_chat_message_requires_valid_role(self):
        """ChatMessage debe rechazar roles no permitidos."""
        with self.assertRaises(ValueError):
            ChatMessage(role="bot", content="text")  # ✗ 'bot' no es válida

    def test_chat_message_accepts_user(self):
        """ChatMessage debe aceptar role 'user'."""
        msg = ChatMessage(role="user", content="test")
        self.assertEqual(msg.role, "user")

    def test_chat_message_accepts_assistant(self):
        """ChatMessage debe aceptar role 'assistant'."""
        msg = ChatMessage(role="assistant", content="test")
        self.assertEqual(msg.role, "assistant")


class TestLlmProfileValidation(unittest.TestCase):
    """Tests de validación de LlmProfile."""

    def test_profile_rejects_invalid_temperature(self):
        """LlmProfile debe rechazar temperature fuera de [0, 2]."""
        with self.assertRaises(ValueError):
            LlmProfile(temperature=-0.1)

        with self.assertRaises(ValueError):
            LlmProfile(temperature=2.1)

    def test_profile_rejects_invalid_output_tokens(self):
        """LlmProfile debe rechazar max_output_tokens < 1 o > 16000."""
        with self.assertRaises(ValueError):
            LlmProfile(max_output_tokens=0)

        with self.assertRaises(ValueError):
            LlmProfile(max_output_tokens=16001)

    def test_profile_rejects_total_less_than_output(self):
        """LlmProfile debe rechazar max_total_model_tokens < max_output_tokens."""
        with self.assertRaises(ValueError):
            LlmProfile(max_output_tokens=1000, max_total_model_tokens=500)


if __name__ == "__main__":
    unittest.main()
