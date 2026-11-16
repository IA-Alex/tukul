"""Unidades de la caché de conversaciones del estado de interfaz (ui_state)."""
import tempfile
import unittest
from pathlib import Path

from tukul_core import storage
from tukul_core.models import ChatMessage
from tukul_ui import ui_state


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

    def test_recorta_los_mensajes_excesivos_en_vez_de_descartarlos(self):
        # Regresión: se descartaban con `continue`, así que una respuesta larga
        # desaparecía del historial sin ninguna señal para el usuario.
        grande = "x" * (ui_state.MAX_CONVERSATION_MESSAGE_CHARS + 1)
        cruda = {"a.md": [
            {"role": "user", "content": grande},
            {"role": "assistant", "content": "válido"},
        ]}
        restaurada = ui_state.restaurar_conversacion(cruda, Path("a.md"))
        self.assertEqual(len(restaurada), 2)
        self.assertEqual(len(restaurada[0].content), ui_state.MAX_CONVERSATION_MESSAGE_CHARS)
        self.assertTrue(restaurada[0].content.endswith(ui_state.MARCA_RECORTE))
        self.assertEqual(restaurada[1].content, "válido")

    def test_nunca_supera_el_presupuesto_total_al_restaurar(self):
        cruda = {"a.md": [
            {"role": "assistant", "content": "y" * ui_state.MAX_CONVERSATION_MESSAGE_CHARS}
            for _ in range(10)
        ]}
        restaurada = ui_state.restaurar_conversacion(cruda, Path("a.md"))
        total = sum(len(item.content) for item in restaurada)
        self.assertLessEqual(total, ui_state.MAX_CONVERSATION_CHARS)
        self.assertTrue(restaurada, "el historial no puede quedar vacío")


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

    def test_conserva_los_turnos_recientes_completos(self):
        # Regresión: el mensaje que excedía el tope se descartaba con `continue`,
        # así que la respuesta del modelo desaparecía sin ninguna señal.
        turnos = [ChatMessage("user", "hola"), ChatMessage("assistant", "conservar")]
        mapa = ui_state.persistir_conversacion({}, Path("a.md"), turnos)
        self.assertEqual(mapa["a.md"], [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "conservar"},
        ])

    def test_una_conversacion_larga_siempre_cabe_en_el_estado(self):
        """Regresión: con 30 turnos de respuestas largas, `save_ui_state` rechazaba
        el archivo entero y la conversación se perdía al reabrir."""
        turnos = []
        for indice in range(15):
            turnos.append(ChatMessage("user", f"pregunta {indice}"))
            turnos.append(ChatMessage("assistant", "a" * ui_state.MAX_CONVERSATION_MESSAGE_CHARS))
        mapa = ui_state.persistir_conversacion({}, Path("a.md"), turnos)
        serializada = ui_state._serializar(mapa)
        self.assertLessEqual(len(serializada.encode("utf-8")), ui_state.MAX_CONVERSATION_CHARS)
        # Y la comprobación definitiva: el archivo real se acepta.
        with tempfile.TemporaryDirectory() as tmp:
            storage.save_ui_state({"conversations": mapa}, Path(tmp) / "config.toml")
        # No se pierde el historial: se conservan los turnos más recientes,
        # empezando por el último que habló el usuario.
        self.assertTrue(mapa["a.md"])
        self.assertEqual(mapa["a.md"][-1]["content"], "a" * ui_state.MAX_CONVERSATION_MESSAGE_CHARS)
        self.assertIn("pregunta 14", [item["content"] for item in mapa["a.md"]])

    def test_un_mensaje_que_excede_el_presupuesto_se_recorta_con_marca(self):
        # Una sola respuesta mayor que todo el presupuesto: el turno se abrevia
        # (conserva su rol y su final) en vez de desaparecer.
        turnos = [
            ChatMessage("user", "pregunta"),
            ChatMessage("assistant", "a" * (ui_state.MAX_CONVERSATION_CHARS * 2)),
        ]
        mapa = ui_state.persistir_conversacion({}, Path("a.md"), turnos)
        self.assertEqual(mapa["a.md"][0]["content"], "pregunta")
        recortada = mapa["a.md"][-1]["content"]
        self.assertLess(len(recortada), ui_state.MAX_CONVERSATION_CHARS * 2)
        self.assertTrue(recortada.endswith(ui_state.MARCA_RECORTE))
        self.assertLessEqual(
            len(ui_state._serializar(mapa).encode("utf-8")), ui_state.MAX_CONVERSATION_CHARS
        )

    def test_el_presupuesto_deriva_del_tamano_real_del_estado(self):
        self.assertLess(ui_state.MAX_CONVERSATION_CHARS, storage.MAX_UI_STATE_BYTES)

    def test_muchos_documentos_nunca_hacen_rechazar_el_guardado(self):
        """Regresión: una cuota por documento no acota el archivo completo.

        Diez documentos, cada uno dentro de su presupuesto, sumaban 10 MB y
        `save_ui_state` rechazaba el archivo entero. Con varios artículos en
        «Recientes» el mismo defecto volvía por la vía global.
        """
        conversaciones: dict = {}
        for indice in range(10):
            turnos = []
            for turno in range(15):
                turnos.append(ChatMessage("user", f"p{turno} " + "x" * 199_995))
                turnos.append(ChatMessage("assistant", "a" * 200_000))
            conversaciones = ui_state.persistir_conversacion(
                conversaciones, Path(f"doc{indice}.md"), turnos)

        with tempfile.TemporaryDirectory() as tmp:
            storage.save_ui_state({"conversations": conversaciones}, Path(tmp) / "config.toml")
        total = len(ui_state._serializar(conversaciones).encode("utf-8"))
        self.assertLessEqual(total, ui_state.MAX_CONVERSATIONS_TOTAL_CHARS)
        self.assertTrue(conversaciones, "no puede quedarse sin ninguna conversación")


class TestPodarConversaciones(unittest.TestCase):
    def test_solo_conserva_los_documentos_vigentes(self):
        mapa = {"a.md": [], "b.md": [], "c.md": []}
        podado = ui_state.podar_conversaciones(mapa, {"a.md", "b.md"})
        self.assertEqual(set(podado), {"a.md", "b.md"})
