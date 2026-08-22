"""Tests de ContextApprovalCache en aislamiento, sin levantar Tk.

Extraída de ArticuladorApp (ver auditoría 2026-08-21): estos casos cubrían
antes el mismo comportamiento pero solo a través de TestAprobacionDeContexto
y TestAprobacionesDesalojoFIFO en tests/test_auditoria_regresion.py, que
necesitan una ventana real. Los que no dependen de Tk quedan acá.
"""
import unittest

from articulador_core.models import LlmProfile
from articulador_ui.context_approval import ContextApprovalCache


def _profile(**overrides) -> LlmProfile:
    base = dict(
        provider="openai_compatible",
        endpoint="https://api.example.com/v1/chat/completions",
        model="m",
        api_key_env="TEST_KEY",
    )
    base.update(overrides)
    return LlmProfile(**base)


class ContextApprovalCacheTests(unittest.TestCase):
    def test_key_for_depende_del_destino_y_del_contenido(self):
        perfil_a = _profile()
        perfil_b = _profile(model="otro-modelo")

        clave_a = ContextApprovalCache.key_for(perfil_a, "paquete", ["notas.md"])
        clave_b = ContextApprovalCache.key_for(perfil_b, "paquete", ["notas.md"])
        clave_contenido_distinto = ContextApprovalCache.key_for(perfil_a, "otro paquete", ["notas.md"])

        self.assertNotEqual(clave_a, clave_b, "Distinto modelo debe dar distinta clave")
        self.assertNotEqual(
            clave_a, clave_contenido_distinto, "Distinto contenido debe dar distinta clave"
        )

    def test_key_for_es_estable_para_el_mismo_destino_y_contenido(self):
        perfil = _profile()
        self.assertEqual(
            ContextApprovalCache.key_for(perfil, "paquete", ["a.md", "b.md"]),
            ContextApprovalCache.key_for(perfil, "paquete", ["a.md", "b.md"]),
        )

    def test_remember_and_contains(self):
        cache = ContextApprovalCache()
        perfil = _profile()
        clave = ContextApprovalCache.key_for(perfil, "paquete", ["notas.md"])

        self.assertNotIn(clave, cache)
        cache.remember(clave)
        self.assertIn(clave, cache)
        self.assertEqual(len(cache), 1)

    def test_remember_for_no_hace_nada_sin_archivos(self):
        cache = ContextApprovalCache()
        cache.remember_for(_profile(), "paquete", [])
        self.assertEqual(len(cache), 0)

    def test_remember_for_registra_con_archivos(self):
        cache = ContextApprovalCache()
        perfil = _profile()
        cache.remember_for(perfil, "paquete", ["notas.md"])
        self.assertIn(ContextApprovalCache.key_for(perfil, "paquete", ["notas.md"]), cache)

    def test_desalojo_fifo_al_llenarse(self):
        cache = ContextApprovalCache(max_size=3)
        cache.remember(("e", "p", "m", ("a",), "h0"))
        cache.remember(("e", "p", "m", ("a",), "h1"))
        cache.remember(("e", "p", "m", ("a",), "h2"))
        self.assertEqual(len(cache), 3)

        cache.remember(("e", "p", "m", ("a",), "h3"))

        self.assertEqual(len(cache), 3, "El tope se mantiene, no crece sin límite")
        self.assertNotIn(("e", "p", "m", ("a",), "h0"), cache, "Se desaloja la más antigua")
        self.assertIn(("e", "p", "m", ("a",), "h3"), cache)

    def test_reinsertar_una_clave_existente_no_la_desaloja(self):
        cache = ContextApprovalCache(max_size=2)
        cache.remember(("e", "p", "m", ("a",), "h0"))
        cache.remember(("e", "p", "m", ("a",), "h1"))

        cache.remember(("e", "p", "m", ("a",), "h0"))  # reinserta la primera

        self.assertEqual(len(cache), 2, "Actualizar una clave presente no debe crecer el tope")
        self.assertIn(("e", "p", "m", ("a",), "h0"), cache)
        self.assertIn(("e", "p", "m", ("a",), "h1"), cache)

    def test_setitem_es_compatible_con_el_uso_como_dict(self):
        """Compatibilidad con el código (y tests) que trataban approved_contexts como dict."""
        cache = ContextApprovalCache()
        clave = ("e", "p", "m", ("a",), "h0")
        cache[clave] = None
        self.assertIn(clave, cache)
        self.assertEqual(len(cache), 1)


if __name__ == "__main__":
    unittest.main()
