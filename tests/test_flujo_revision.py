"""Flujo de revisión y de conversación: qué se envía y qué se muestra.

Ejecutan `review()`, `_solicitar_revision()` y `finish()` reales. Los defectos
que fijan estas pruebas se observaron en la interfaz:

- «Revisar artículo» pasaba por el flujo general, así que indexaba el workspace,
  proponía compartir README.md o NEXT_STEPS.md y se quedaba bloqueado en
  «Preparando contexto · esperando tu confirmación».
- El prompt técnico de revisión aparecía en la conversación como si lo hubiera
  escrito el usuario, con su JSON crudo.
- La respuesta de la revisión (JSON) se pintaba en el historial.
- Un «Hola» sin coincidencias ofrecía compartir archivos por repliegue.
"""
import json
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core.prompting import REVIEW_PROMPT
from tukul_ui.app import TukulApp
from tukul_ui.estado import EstadoUI
from tukul_ui.worker_threads import WorkerThreads

RESPUESTA_VALIDA = json.dumps({"findings": [
    {"category": "gramática", "severity": "alta", "original": "floja",
     "suggestion": "poco sólida", "reason": "registro coloquial"},
    {"category": "redundancia", "severity": "baja", "original": "conviene recortarla",
     "suggestion": "conviene acortarla", "reason": "repite la idea"},
]}, ensure_ascii=False)


def _esperar_llamada(app: TukulApp, mock_obj, timeout: float = 2.0) -> None:
    """Espera a que el hilo en segundo plano invoque el mock parcheado.

    `review()`/`request()`/`send_message()`/`confirm_and_send()` lanzan un hilo
    daemon que llama a `self.llm.stream_response`. Sin esta espera, el `with
    patch.object(...)` podía deshacer el parche antes de que el hilo arrancara
    a ejecutarlo: entonces caía al método real, una petición de red genuina
    (con los reintentos y el backoff de la v0.2.1) que sobrevivía minutos y
    terminaba abortando un test completamente distinto, ya con la interfaz de
    Tk destruida. Se espera aquí, DENTRO del bloque del parche.
    """
    limite = time.monotonic() + timeout
    while not mock_obj.called and time.monotonic() < limite:
        app.update()
        time.sleep(0.01)
    assert mock_obj.called, "El hilo en segundo plano no invocó el mock a tiempo"


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
        self.app = TukulApp(config)
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
    def test_revisar_no_muestra_la_barra_de_confirmacion(self):
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
            self._asentar()
        self.assertFalse(self.app.panel_asistente.barra_aprobacion.winfo_ismapped(),
                         "No hay contexto que aprobar: la barra no debe aparecer")

    # --- 2. el prompt técnico no llega al historial ---------------------
    def test_revisar_no_escribe_el_prompt_interno_en_el_historial(self):
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
            self._asentar()

        historial = self._historial()
        self.assertNotIn(REVIEW_PROMPT, historial)
        self.assertNotIn('"findings"', historial, "Nada de JSON en la conversación")
        self.assertNotIn("SOLO JSON", historial)
        self.assertEqual([m.content for m in self.app.session.conversation], [],
                         "El prompt técnico tampoco entra en la conversación guardada")

    # --- 3. envía el texto correcto ------------------------------------
    def test_revisar_envia_el_articulo_completo(self):
        with patch.object(self.app.llm, "stream_response", return_value=None) as enviar:
            self.app.review()
            _esperar_llamada(self.app, enviar)
            self._asentar()

        enviado = enviar.call_args[0][2]  # (profile, api_key, article, packet, conv)
        self.assertEqual(enviado, self.app.editor.get("1.0", "end-1c"))
        self.assertEqual(enviar.call_args[0][3], "", "Sin paquete de contexto local")

    def test_revisar_envia_solo_la_seleccion_cuando_la_hay(self):
        self.app.editor.tag_add("sel", "1.0", "1.16")
        seleccion = self.app.editor.get("sel.first", "sel.last")
        with patch.object(self.app.llm, "stream_response", return_value=None) as enviar:
            self.app.review()
            _esperar_llamada(self.app, enviar)
            self._asentar()

        self.assertEqual(enviar.call_args[0][2], seleccion)
        self.assertNotEqual(seleccion, self.app.editor.get("1.0", "end-1c"))

    def test_el_estado_indica_el_ambito_revisado(self):
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
            self._asentar()
        self.assertIn("revisando el artículo", self.app.activity_var.get())

        self.app.session.request_active = False
        self.app.editor.tag_add("sel", "1.0", "1.16")
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
            self._asentar()
        self.assertIn("revisando la selección", self.app.activity_var.get())

    # --- 5. resultado legible, sin JSON --------------------------------
    def test_una_revision_valida_abre_los_hallazgos_sin_pintar_json(self):
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
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
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
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
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
            self._asentar()
        request_id = self.app.generation_counter
        basura = "Claro, aquí van mis comentarios sobre el texto..."

        self.app.chunks.append(request_id, basura)
        self.app.control_queue.put_nowait(
            ("complete", request_id, basura, [], (None, None), "review"))
        self.app.process_ui_events()
        self._asentar()

        historial = self._historial()
        self.assertIn("respondió en prosa", historial,
                      "La causa se nombra: no era falta de hallazgos")
        self.assertNotIn(basura, historial, "Ni la respuesta cruda ni el prompt")
        self.assertIs(self.app.estado_actual, EstadoUI.ERROR)
        self.assertFalse(self.app.session.request_active)
        self.assertEqual(self.app.review_dialogs, [], "No se abre un diálogo vacío")

    def test_un_articulo_sin_hallazgos_no_es_un_error(self):
        """Un `findings` vacío es un resultado correcto, no un fallo del modelo."""
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.review()
            _esperar_llamada(self.app, self.app.llm.stream_response)
            self._asentar()
        request_id = self.app.generation_counter
        limpio = json.dumps({"findings": []})

        self.app.chunks.append(request_id, limpio)
        self.app.control_queue.put_nowait(
            ("complete", request_id, limpio, [], (None, None), "review"))
        self.app.process_ui_events()
        self._asentar()

        historial = self._historial()
        self.assertIn("no se encontraron hallazgos", historial)
        self.assertIs(self.app.estado_actual, EstadoUI.EXITO)
        self.assertFalse(self.app.session.request_active)


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
        self.app = TukulApp(config)
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
        with patch.object(self.app.llm, "stream_response", return_value=None) as enviar:
            self.app.request("¿Cómo mejoro la tesis?")
            _esperar_llamada(self.app, enviar)
            for _ in range(5):
                self.app.update()
        self.assertEqual(
            enviar.call_args[0][2],
            self.app.editor.get("1.0", "end-1c"),
            "El LLM recibe el artículo visible, no un campo vacío",
        )
        self.assertEqual(enviar.call_args[0][3], "", "No envía archivos locales")

    def test_un_mensaje_normal_si_aparece_en_el_historial(self):
        # Con el placeholder activo el input ignora el envío: hay que escribir
        # como lo haría la persona (el primer foco lo retira).
        self.app._placeholder_activo = False
        self.app.input.delete("1.0", "end")
        self.app.input.insert("1.0", "¿Cómo mejoro la tesis?")
        with patch.object(self.app.llm, "stream_response", return_value=None) as enviar:
            self.app.send_message()
            _esperar_llamada(self.app, enviar)
            for _ in range(10):
                self.app.update()
        self.assertIn("¿Cómo mejoro la tesis?", self.app.history.get("1.0", "end-1c"))

    def test_sin_archivos_relevantes_no_se_pide_confirmacion(self):
        self.app.generation_counter += 1
        rid = self.app.generation_counter
        self.app.request_types[rid] = "normal"
        with patch.object(self.app.llm, "stream_response", return_value=None) as enviar:
            self.app.confirm_and_send(rid, "Hola", "artículo", "", [], threading.Event())
            _esperar_llamada(self.app, enviar)
            for _ in range(5):
                self.app.update()
        self.assertFalse(self.app.panel_asistente.barra_aprobacion.winfo_ismapped())

    def test_articulo_anterior_autorizado_se_envia_sin_segunda_confirmacion(self):
        anterior = self.raiz / "articulo-anterior.md"
        anterior.write_text("La tesis anterior trataba seguridad y criterio.", encoding="utf-8")
        actual = self.raiz / "articulo-actual.md"
        actual.write_text("Artículo actual sobre criterio humano.", encoding="utf-8")
        self.app.load_document(anterior)
        self.assertTrue(self.app._add_current_article_to_context())
        self.app._authorize_context_articles()
        self.app.load_document(actual)
        self.assertEqual(self.app.references_button.cget("text"), "Contexto: 1 artículo")

        with patch.object(self.app.llm, "stream_response", return_value=None) as enviar:
            self.app.request("Compara ambos artículos")
            _esperar_llamada(self.app, enviar)
            self._asentar()
            self.assertFalse(self.app.panel_asistente.barra_aprobacion.winfo_ismapped(),
                             "Aceptar al conservar no puede pedir permiso otra vez")

        # El activo y el previo viajan por campos distintos del prompt.
        self.assertEqual(enviar.call_args[0][2], "Artículo actual sobre criterio humano.")
        self.assertIn("ARTÍCULO DE CONTEXTO: articulo-anterior.md", enviar.call_args[0][3])
        self.assertIn("tesis anterior", enviar.call_args[0][3])

    def test_cambiar_modelo_vuelve_a_requerir_autorizacion(self):
        anterior = self.raiz / "articulo-anterior.md"
        anterior.write_text("Contexto previo.", encoding="utf-8")
        self.app.load_document(anterior)
        self.app._add_current_article_to_context()
        self.app._authorize_context_articles()
        self.app.profile.model = "otro-modelo"

        # Este camino se detiene en la barra de aprobación: nunca llega a
        # invocar stream_response, así que no hay hilo que esperar aquí.
        with patch.object(self.app.llm, "stream_response", return_value=None):
            self.app.request("Consulta")
            self._asentar()

        self.assertTrue(self.app.panel_asistente.barra_aprobacion.winfo_ismapped(),
                        "Un modelo distinto es otro destino de autorización")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestErrorDeGeneracionDeIdeas(unittest.TestCase):
    """El fallo del pipeline de CVEs debe llegar al usuario, no morir en un lambda.

    Regresión de un `NameError` real: las ramas de error de
    `_fetch_impact_suggestion` diferían `self.after(0, lambda: ...(error))`.
    Python borra la variable del `except` al salir del bloque, así que el lambda
    reventaba al ejecutarse desde el bucle de Tk: el logger sí registraba el
    fallo, pero el usuario no veía nada y el diálogo quedaba colgado.

    El fix está aplicado (`_publicar_error_ideas` materializa `mensaje` antes de
    diferirlo); estos tests lo fijan para que no regrese.
    """

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        config = self.raiz / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\n'
            'endpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "CLAVE_PRUEBA_IDEAS"\n',
            encoding="utf-8")
        os.environ["CLAVE_PRUEBA_IDEAS"] = "clave"
        self.app = TukulApp(config)
        for _ in range(5):
            self.app.update()
        self.dialogo = tk.Toplevel(self.app)

    def tearDown(self):
        try:
            self.dialogo.destroy()
        except tk.TclError:
            pass
        self.app.destroy()
        self.directorio.cleanup()
        os.environ.pop("CLAVE_PRUEBA_IDEAS", None)

    def _error_del_pipeline(self, excepcion: Exception) -> list[tuple]:
        """Lanza el pipeline con `excepcion` y devuelve los callbacks diferidos.

        No espera al bucle de Tk: captura lo que `after(0, ...)` deja pendiente y
        lo ejecuta aquí, de modo que un `NameError` en el lambda se ve de
        inmediato y no como un cuelgue silencioso.
        """
        import tukul_ui.app as modulo

        # El worker corre en otro hilo y, correctamente, no programa `after`
        # desde ahí (eso aborta el intérprete en CPython 3.13). Aquí se simula
        # el hilo de Tk para capturar lo que dejaría pendiente.
        diferidos: list = []
        original_after = self.app.after

        def _after(ms, funcion=None, *args):
            if funcion is not None:
                diferidos.append(funcion)
                return "id-falso"
            return original_after(ms)

        class _OrquestadorQueFalla:
            def __init__(self, **_kwargs):
                pass

            def fetch_all(self, **_kwargs):
                raise excepcion

        errores: list[tuple] = []
        self.app._on_impact_suggestion_error = lambda *a, **k: errores.append(a)

        with patch.object(modulo, "FeedOrchestrator", _OrquestadorQueFalla), \
             patch.object(modulo.messagebox, "askyesno", return_value=True), \
             patch.object(modulo, "_en_el_hilo_de_tk", return_value=True), \
             patch.object(self.app, "after", side_effect=_after):
            self.app._fetch_impact_suggestion(self.dialogo, lambda: None)
            # El pipeline corre en un hilo daemon: se espera a que termine.
            WorkerThreads.esperar(5)

        for funcion in diferidos:
            funcion()
        return errores

    def test_un_runtimeerror_del_orquestador_llega_al_usuario(self):
        """Fallo de red: el mensaje se muestra en vez de lanzar NameError."""
        errores = self._error_del_pipeline(RuntimeError("Ninguna fuente respondió"))
        self.assertEqual(len(errores), 1, "Debe informarse exactamente un error")
        self.assertIn("Ninguna fuente respondió", errores[0][1])

    def test_un_error_inesperado_llega_al_usuario(self):
        """Fallo genérico: también se informa, con el prefijo esperado."""
        errores = self._error_del_pipeline(ValueError("json corrupto"))
        self.assertEqual(len(errores), 1, "Debe informarse exactamente un error")
        self.assertIn("Error inesperado", errores[0][1])
        self.assertIn("json corrupto", errores[0][1])


if __name__ == "__main__":
    unittest.main()
