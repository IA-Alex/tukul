"""Unidades de la caché de conversaciones del estado de interfaz (ui_state)."""
import unittest
from pathlib import Path

from articulador_core.models import ChatMessage
from articulador_ui import ui_state


class TestRestaurarConversacion(unittest.TestCase):
    def test_devuelve_vacia_sin_ruta(self):
        self.assertEqual(ui_state.restaurar_conversacion({}, None), [])

    def test_devuelve_vacia_si_el_estado_no_es_dict(self):
        self.assertEqual(ui_state.restaurar_conversacion(["no-dict"], Path("a.md")), [])

    def test_restaura_y_descarta_items_malformados(self):
        cruda = {
            "a.md": [
                {"role": "user", "content": "hola"},
                "basura",
                {"role": "sistema", "content": "x"},
                {"role": "assistant", "content": "mundo"},
            ]
        }
        restaurada = ui_state.restaurar_conversacion(cruda, Path("a.md"))
        self.assertEqual(
            restaurada, [ChatMessage("user", "hola"), ChatMessage("assistant", "mundo")]
        )

    def test_devuelve_vacia_para_documento_sin_conversacion(self):
        self.assertEqual(ui_state.restaurar_conversacion({}, Path("sin.md")), [])

    def test_descarta_mensajes_excesivos_y_respeta_tope_total(self):
        grande = "x" * (ui_state.MAX_CONVERSATION_MESSAGE_CHARS + 1)
        cruda = {"a.md": [
            {"role": "user", "content": grande},
            {"role": "assistant", "content": "válido"},
        ]}
        restaurada = ui_state.restaurar_conversacion(cruda, Path("a.md"))
        self.assertEqual([item.content for item in restaurada], ["válido"])


class TestPersistirConversacion(unittest.TestCase):
    def test_recorta_a_los_ultimos_turnos(self):
        turnos = [ChatMessage("user", f"m{i}") for i in range(35)]
        mapa = ui_state.persistir_conversacion({}, Path("a.md"), turnos)
        self.assertEqual(len(mapa["a.md"]), 30)

    def test_no_pisa_conversaciones_de_otros_documentos(self):
        previo = {"otro.md": [{"role": "user", "content": "x"}]}
        mapa = ui_state.persistir_conversacion(previo, Path("a.md"), [ChatMessage("user", "hola")])
        self.assertEqual(mapa["otro.md"], [{"role": "user", "content": "x"}])
        self.assertEqual(mapa["a.md"], [{"role": "user", "content": "hola"}])

    def test_estado_corrupto_no_dict_se_trata_como_vacio(self):
        mapa = ui_state.persistir_conversacion(["no-dict"], Path("a.md"), [])
        self.assertEqual(mapa["a.md"], [])

    def test_no_persiste_un_mensaje_que_supera_el_limite(self):
        turnos = [
            ChatMessage("user", "x" * (ui_state.MAX_CONVERSATION_MESSAGE_CHARS + 1)),
            ChatMessage("assistant", "conservar"),
        ]
        mapa = ui_state.persistir_conversacion({}, Path("a.md"), turnos)
        self.assertEqual(mapa["a.md"], [{"role": "assistant", "content": "conservar"}])


class TestPodarConversaciones(unittest.TestCase):
    def test_solo_conserva_los_documentos_vigentes(self):
        mapa = {"a.md": [], "b.md": [], "c.md": []}
        podado = ui_state.podar_conversaciones(mapa, {"a.md", "b.md"})
        self.assertEqual(set(podado), {"a.md", "b.md"})
