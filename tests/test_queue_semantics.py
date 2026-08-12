"""Validación de entrada: parser de revisiones, ChatMessage y LlmProfile.

Las clases de semántica de colas y de granularidad de aprobación que vivían aquí
se eliminaron en la auditoría: no ejecutaban código de producción (construían
tuplas locales y afirmaban sobre ellas) y describían una arquitectura de dos
colas y un banner que la aplicación nunca tuvo. Su cobertura real vive ahora en
tests/test_auditoria_regresion.py.
"""
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
