"""Flujo de revisión y de conversación: qué se envía y qué se muestra.

Ejecutan `review()`, `_solicitar_revision()`, `finish()` y `ContextIndex.packet()`
reales. Los defectos que fijan estas pruebas se observaron en la interfaz:

- «Revisar artículo» pasaba por el flujo general, así que indexaba el workspace,
  proponía compartir README.md o NEXT_STEPS.md y se quedaba bloqueado en
  «Preparando contexto · esperando tu confirmación».
- El prompt técnico de revisión aparecía en la conversación como si lo hubiera
  escrito el usuario, con su JSON crudo.
- La respuesta de la revisión (JSON) se pintaba en el historial.
- Un «Hola» sin coincidencias ofrecía compartir archivos por repliegue.
"""
import json
import sys
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from articulador_core.context import ContextIndex
from articulador_ui.app import REVIEW_PROMPT, ArticuladorApp
from articulador_ui.estado import EstadoUI

RESPUESTA_VALIDA = json.dumps({"findings": [
    {"category": "gramática", "severity": "alta", "original": "floja",
     "suggestion": "poco sólida", "reason": "registro coloquial"},
    {"category": "redundancia", "severity": "baja", "original": "conviene recortarla",
     "suggestion": "conviene acortarla", "reason": "repite la idea"},
]}, ensure_ascii=False)


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestFlujoDeRevision(unittest.TestCase):
    """La revisión va directa al modelo con el texto que se ve en pantalla."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        # Ruido técnico del repositorio: es lo que la revisión ofrecía compartir.
        (self.raiz / "README.md").write_text("Instalación y uso del proyecto", encoding="utf-8")
        (self.raiz / "NEXT_STEPS.md").write_text("Pasos siguientes del proyecto", encoding="utf-8")
        self.documento = self.raiz / "articulo.md"
        self.documento.write_text("La introducción es floja y conviene recortarla.",
                                  encoding="utf-8")
        config = self.raiz / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\n'
            'endpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "CLAVE_PRUEBA_REVISION"\n',
            encoding="utf-8")
        import os
        os.environ["CLAVE_PRUEBA_REVISION"] = "clave"
        self.app = ArticuladorApp(config, self.raiz)
        self.app.load_document(self.documento)
        self._asentar()

    def tearDown(self):
        import os
        self.app.destroy()
        self.directorio.cleanup()
        os.environ.pop("CLAVE_PRUEBA_REVISION", None)

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _historial(self) -> str:
        return self.app.history.get("1.0", "end-1c")

    # --- 1. no busca contexto local ------------------------------------
    def test_revisar_no_prepara_contexto_local(self):
        with patch.object(self.app.context, "prepare_context") as buscar, \
             patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()

        buscar.assert_not_called()
        self.assertEqual(self.app.scope.context_files, [],
                         "La revisión no debe proponer archivos locales")

    def test_revisar_no_muestra_la_barra_de_confirmacion(self):
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()
        self.assertFalse(self.app.barra_aprobacion.winfo_ismapped(),
                         "No hay contexto que aprobar: la barra no debe aparecer")

    # --- 2. el prompt técnico no llega al historial ---------------------
    def test_revisar_no_escribe_el_prompt_interno_en_el_historial(self):
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()

        historial = self._historial()
        self.assertNotIn(REVIEW_PROMPT, historial)
        self.assertNotIn('"findings"', historial, "Nada de JSON en la conversación")
        self.assertNotIn("SOLO JSON", historial)
        self.assertEqual([m.content for m in self.app.session.conversation], [],
                         "El prompt técnico tampoco entra en la conversación guardada")

    # --- 3. envía el texto correcto ------------------------------------
    def test_revisar_envia_el_articulo_completo(self):
        with patch.object(self.app.llm, "stream_response") as enviar:
            self.app.review()
            self._asentar()

        enviado = enviar.call_args[0][2]  # (profile, api_key, article, packet, conv)
        self.assertEqual(enviado, self.app.editor.get("1.0", "end-1c"))
        self.assertEqual(enviar.call_args[0][3], "", "Sin paquete de contexto local")

    def test_revisar_envia_solo_la_seleccion_cuando_la_hay(self):
        self.app.editor.tag_add("sel", "1.0", "1.16")
        seleccion = self.app.editor.get("sel.first", "sel.last")
        with patch.object(self.app.llm, "stream_response") as enviar:
            self.app.review()
            self._asentar()

        self.assertEqual(enviar.call_args[0][2], seleccion)
        self.assertNotEqual(seleccion, self.app.editor.get("1.0", "end-1c"))

    def test_el_estado_indica_el_ambito_revisado(self):
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()
        self.assertIn("revisando el artículo", self.app.activity.get())

        self.app.session.request_active = False
        self.app.editor.tag_add("sel", "1.0", "1.16")
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()
        self.assertIn("revisando la selección", self.app.activity.get())

    # --- 5. resultado legible, sin JSON --------------------------------
    def test_una_revision_valida_abre_los_hallazgos_sin_pintar_json(self):
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()
        request_id = self.app.generation_counter

        # El modelo responde por el canal de chunks y cierra por el de control.
        self.app.chunks.append(request_id, RESPUESTA_VALIDA)
        self.app.control_queue.put_nowait(
            ("complete", request_id, RESPUESTA_VALIDA, [], (None, None), "review"))
        self.app.process_ui_events()
        self._asentar()

        historial = self._historial()
        self.assertNotIn('"findings"', historial, "El JSON no puede llegar al historial")
        self.assertNotIn("suggestion", historial)
        self.assertIn("2 hallazgos", historial, "Debe resumirse en lenguaje humano")
        self.assertEqual(len(self.app.review_dialogs), 1, "Se abre la revisión estructurada")
        self.assertTrue(self.app.review_dialogs[0].winfo_exists())
        self.assertEqual([m.content for m in self.app.session.conversation], [],
                         "El JSON tampoco se guarda como contexto de la conversación")

    # --- 6. error legible y UI utilizable ------------------------------
    def test_un_error_de_revision_es_legible_y_devuelve_la_ui(self):
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()
        request_id = self.app.generation_counter

        self.app.control_queue.put_nowait(
            ("error", request_id, "No pude responder: tiempo agotado", []))
        self.app.process_ui_events()
        self._asentar()

        historial = self._historial()
        self.assertIn("No se pudo revisar", historial)
        self.assertNotIn(REVIEW_PROMPT, historial)
        self.assertIs(self.app.estado_actual, EstadoUI.ERROR)
        self.assertFalse(self.app.session.request_active)
        self.assertNotIn("disabled", self.app.send_button.state(),
                         "La interfaz vuelve a ser utilizable")

    def test_una_respuesta_no_json_no_muestra_nada_tecnico(self):
        with patch.object(self.app.llm, "stream_response"):
            self.app.review()
            self._asentar()
        request_id = self.app.generation_counter
        basura = "Claro, aquí van mis comentarios sobre el texto..."

        self.app.chunks.append(request_id, basura)
        self.app.control_queue.put_nowait(
            ("complete", request_id, basura, [], (None, None), "review"))
        self.app.process_ui_events()
        self._asentar()

        historial = self._historial()
        self.assertIn("no devolvió una revisión utilizable", historial)
        self.assertNotIn(basura, historial, "Ni la respuesta cruda ni el prompt")
        self.assertIs(self.app.estado_actual, EstadoUI.ERROR)
        self.assertFalse(self.app.session.request_active)
        self.assertEqual(self.app.review_dialogs, [], "No se abre un diálogo vacío")


class TestContextoSinRepliegue(unittest.TestCase):
    """Sin coincidencias no se propone nada: no hay repliegue por nombre."""

    def _indice(self) -> tuple[ContextIndex, Path]:
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        raiz = Path(directorio.name)
        (raiz / "README.md").write_text("Instalación y uso del proyecto", encoding="utf-8")
        (raiz / "NEXT_STEPS.md").write_text("Pasos siguientes del proyecto", encoding="utf-8")
        (raiz / "notas.md").write_text("apuntes sobre la tesis del artículo", encoding="utf-8")
        return ContextIndex(raiz), raiz

    # --- 4. "Hola" no pide compartir nada -------------------------------
    def test_un_saludo_no_propone_ningun_archivo(self):
        indice, _raiz = self._indice()
        packet, files = indice.packet("Hola", 4_000)
        self.assertEqual(files, [], "Un saludo no justifica compartir archivos")
        self.assertEqual(packet, "")

    def test_una_consulta_sin_coincidencias_no_propone_archivos_tecnicos(self):
        indice, _raiz = self._indice()
        _packet, files = indice.packet("xyzzy plugh", 4_000)
        self.assertEqual(files, [])
        self.assertNotIn("README.md", files)
        self.assertNotIn("NEXT_STEPS.md", files)

    def test_una_consulta_relevante_si_propone_su_archivo(self):
        indice, _raiz = self._indice()
        _packet, files = indice.packet("tesis del artículo", 4_000)
        self.assertIn("notas.md", files, "La relevancia real sí debe proponerse")

    def test_sin_archivos_no_hay_confirmacion_de_privacidad(self):
        """La barra solo tiene sentido si de verdad se va a compartir algo."""
        indice, _raiz = self._indice()
        _packet, files = indice.packet("Hola", 4_000)
        # Reproduce la condición exacta de confirm_and_send.
        self.assertFalse(bool(files), "Sin archivos no se pide confirmación")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestMensajeNormalConservaSuFlujo(unittest.TestCase):
    """El artículo visible es directo; las referencias son siempre explícitas."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        (self.raiz / "notas.md").write_text("apuntes sobre la tesis", encoding="utf-8")
        config = self.raiz / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\n'
            'endpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "CLAVE_PRUEBA_NORMAL"\n',
            encoding="utf-8")
        import os
        os.environ["CLAVE_PRUEBA_NORMAL"] = "clave"
        self.app = ArticuladorApp(config, self.raiz)
        for _ in range(5):
            self.app.update()

    def tearDown(self):
        import os
        self.app.destroy()
        self.directorio.cleanup()
        os.environ.pop("CLAVE_PRUEBA_NORMAL", None)

    def _asentar(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_un_mensaje_normal_no_explora_el_workspace(self):
        with patch.object(self.app.context, "prepare_context") as buscar, \
             patch.object(self.app.llm, "stream_response") as enviar:
            self.app.request("¿Cómo mejoro la tesis?")
            for _ in range(5):
                self.app.update()
        buscar.assert_not_called()
        self.assertEqual(
            enviar.call_args[0][2],
            self.app.editor.get("1.0", "end-1c"),
            "El LLM recibe el artículo visible, no un campo vacío",
        )
        self.assertEqual(enviar.call_args[0][3], "", "No envía archivos locales")

    def test_un_mensaje_normal_si_aparece_en_el_historial(self):
        self.app.input.insert("1.0", "¿Cómo mejoro la tesis?")
        with patch.object(self.app.llm, "stream_response"):
            self.app.send_message()
            for _ in range(10):
                self.app.update()
        self.assertIn("¿Cómo mejoro la tesis?", self.app.history.get("1.0", "end-1c"))

    def test_sin_archivos_relevantes_no_se_pide_confirmacion(self):
        self.app.generation_counter += 1
        rid = self.app.generation_counter
        self.app.request_types[rid] = "normal"
        with patch.object(self.app.llm, "stream_response"):
            self.app.confirm_and_send(rid, "Hola", "artículo", "", [], threading.Event())
            for _ in range(5):
                self.app.update()
        self.assertFalse(self.app.barra_aprobacion.winfo_ismapped())

    def test_referencias_elegidas_se_conservan_y_piden_confirmacion(self):
        anterior = self.raiz / "articulo-anterior.md"
        anterior.write_text("La tesis anterior trataba seguridad y criterio.", encoding="utf-8")
        self.app.editor.insert("1.0", "Artículo actual sobre criterio humano.")
        self.assertEqual(self.app._add_references([str(anterior)]), 1)
        self.assertEqual(self.app._add_references([str(anterior)]), 0, "No duplica una referencia")
        self.assertEqual(self.app.references_button.cget("text"), "Referencias: 1")

        with patch.object(self.app.llm, "stream_response") as enviar:
            self.app.request("Compara ambos artículos")
            self._asentar()
            self.assertTrue(self.app.barra_aprobacion.winfo_ismapped())
            self.assertIn("articulo-anterior.md", self.app.aprobacion_texto.get())
            enviar.assert_not_called()

            self.app.boton_aprobar.invoke()
            self._asentar()

        # `Text.get("1.0", "end-1c")` descarta el salto de línea final implícito
        # que Tk mantiene siempre, así que el artículo viaja sin él.
        self.assertEqual(enviar.call_args[0][2], "Artículo actual sobre criterio humano.")
        self.assertIn("REFERENCIA LOCAL: articulo-anterior.md", enviar.call_args[0][3])
        self.assertIn("tesis anterior", enviar.call_args[0][3])


if __name__ == "__main__":
    unittest.main()
