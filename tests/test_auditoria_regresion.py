"""Regresiones de la auditoría estructural.

A diferencia de otros módulos de tests de este repo, cada prueba de aquí ejecuta
código de producción: si se revierte la corrección, la prueba falla.

Cobertura:
- El bombeo de eventos de UI sobrevive al fallo de un manejador.
- Un documento recién cargado no queda marcado como sucio.
- La salida parcial se conserva cuando el streaming termina en error.
- atomic_write preserva los permisos del destino.
- save_project explica la restricción de rutas en vez de filtrar un ValueError.
- La huella de aprobación de contexto es estable entre mensajes.
- validate_endpoint impide sacar la API key del transporte cifrado.
- Las redirecciones HTTP no reenvían la API key a otro origen.
- complete() acota la memoria de la respuesta no streaming.
"""
import io
import os
import queue
import stat
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core import storage
from tukul_core.llm import LLMClient, LlmError, validate_endpoint
from tukul_core.models import ArticleSession, LlmProfile
from tukul_ui.app import TukulApp
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import EstadoUI


def _esperar_hilo_de_envio(app: TukulApp, desde: int = 0, timeout: float = 5.0) -> None:
    """Espera a que el hilo daemon de `confirm_and_send` invoque `app.llm.stream_response`.

    `confirm_and_send()` lanza un hilo real; mantener el parche activo hasta
    `tearDown` no basta si el hilo ni siquiera ha empezado a ejecutarse cuando
    el test termina. Sin esta espera, ese hilo puede seguir sin arrancar
    minutos después —bajo la carga de la suite completa— y aparecer en medio
    de un test totalmente distinto, colisionando con Tk desde otro hilo.

    El límite se subió de 2.0s a 5.0s: 2s resultaba insuficiente en algunas
    ejecuciones bajo cobertura (`--cov`) con la suite completa ya corrida en
    el mismo proceso. Sigue habiendo un caso residual —solo reproducido con
    `--cov` + `--junitxml` + los 221 tests juntos, nunca en aislamiento— donde
    la espera se agota igualmente; ver la nota de la auditoría 2026-08-21 en
    el historial de commits antes de subir este número de nuevo: no parece
    ser una cuestión de cuánto se espera, sino de orden/composición de la
    suite, y merece su propia investigación en vez de un timeout mayor.

    `desde` es el `call_count` antes de invocar `confirm_and_send`: un mismo
    test puede enviar varias veces sobre el mismo mock, así que comprobar solo
    `.called` no distinguiría un envío nuevo de uno anterior ya resuelto.
    """
    mock_obj = app.llm.stream_response
    limite = time.monotonic() + timeout
    while mock_obj.call_count <= desde and time.monotonic() < limite:
        app.update()
        time.sleep(0.01)
    assert mock_obj.call_count > desde, "El hilo de confirm_and_send no invocó el mock a tiempo"


class _Var:
    """StringVar mínimo: los ayudantes sin ventana no tienen raíz Tk."""

    def __init__(self, valor: str = "") -> None:
        self._valor = valor

    def set(self, valor) -> None:
        self._valor = valor

    def get(self):
        return self._valor


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


HAS_DISPLAY = _display_available()


def _headless_app() -> TukulApp:
    """App con el estado mínimo de una petición, sin construir widgets reales."""
    app = TukulApp.__new__(TukulApp)
    app.closing = False
    app.control_queue = queue.Queue()
    app.chunks = ChunkBuffer()
    app.request_types = {}
    app.streaming_request = None
    app.streaming_text = ""
    app.scope = DocumentScope()
    app.estado_actual = EstadoUI.REPOSO
    app.activity_var = _Var(EstadoUI.REPOSO.etiqueta())
    app.estado_ayuda_var = _Var(EstadoUI.REPOSO.ayuda)
    app.estado_label = Mock()
    app.history = Mock()
    app.activity_var = Mock()
    app.status = Mock()
    app.cost_label_var = Mock()
    app.send_button = Mock()
    app.cancel_button = Mock()
    app.after = Mock()
    app.stream_chunk = Mock()
    app.docs = Mock()
    app.docs.session = ArticleSession()
    return app


class TestBombeoDeEventosResiliente(unittest.TestCase):
    """El pump nunca debe morir: si no se reprograma, la app queda sorda."""

    def test_pump_se_reprograma_aunque_falle_un_manejador(self):
        app = _headless_app()
        app.request_types[1] = "normal"
        # usage=None revienta finish() al formatear el uso real.
        app.control_queue.put_nowait(("complete", 1, "ok", [], None, "normal"))

        app.process_ui_events()

        self.assertTrue(app.after.called, "El bombeo debe reprogramarse pese al fallo")
        self.assertEqual(app.after.call_args[0][1], app.process_ui_events)

    def test_un_evento_roto_no_impide_procesar_los_siguientes(self):
        app = _headless_app()
        app.request_types[1] = "normal"
        app.request_types[2] = "normal"
        app.control_queue.put_nowait(("complete", 1, "ok", [], None, "normal"))
        app.chunks.append(2, "hola")

        app.process_ui_events()

        self.assertEqual(app.control_queue.qsize(), 0, "La cola de control debe quedar drenada")
        app.stream_chunk.assert_called_with(2, "hola")

    def test_fallo_de_manejador_libera_la_peticion(self):
        app = _headless_app()
        app.request_types[1] = "normal"
        app.docs.session.request_active = True
        app.control_queue.put_nowait(("complete", 1, "ok", [], None, "normal"))

        app.process_ui_events()

        self.assertNotIn(1, app.request_types)
        app.send_button.state.assert_any_call(["!disabled"])
        app.cancel_button.state.assert_any_call(["disabled"])


class TestSalidaParcialEnError(unittest.TestCase):
    """Un error tras N chunks no debe dejar el mensaje cortado sin explicación."""

    def test_error_tras_streaming_conserva_lo_recibido(self):
        app = _headless_app()
        app.request_types[7] = "normal"
        app.streaming_request = 7
        app.streaming_text = "respuesta a medias"
        app._append_notice = Mock()

        app.finish(7, "No pude responder: timeout", [], (None, None), "normal", is_error=True)

        self.assertEqual(app.scope.last_response, "respuesta a medias")
        self.assertEqual(
            [m.content for m in app.docs.session.conversation], ["respuesta a medias"]
        )
        app._append_notice.assert_called_once()
        self.assertIn("[INCOMPLETO]", app._append_notice.call_args[0][0])

    def test_error_sin_streaming_muestra_el_mensaje_de_error(self):
        app = _headless_app()
        app.request_types[8] = "normal"
        app.append = Mock()

        app.finish(8, "No pude responder: timeout", [], (None, None), "normal", is_error=True)

        app.append.assert_called_once_with("Tukul", "No pude responder: timeout")
        self.assertEqual(list(app.docs.session.conversation), [])

    def test_exito_guarda_el_resultado_completo(self):
        app = _headless_app()
        app.request_types[9] = "normal"
        app.streaming_request = 9
        app.streaming_text = "hola"

        app.finish(9, "hola mundo", [], (10, 5), "normal")

        self.assertEqual(app.scope.last_response, "hola mundo")
        self.assertEqual([m.content for m in app.docs.session.conversation], ["hola mundo"])
        self.assertEqual(app.streaming_text, "")


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestDocumentoRecienAbierto(unittest.TestCase):
    """Tk encola <<Modified>> de forma asíncrona: cargar no es editar."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_cargar_documento_no_lo_marca_como_sucio(self):
        document = self.root / "a.md"
        document.write_text("hola mundo", encoding="utf-8")
        self.app.load_document(document)

        self._settle()

        self.assertFalse(self.app.session.dirty)
        self.assertEqual(self.app.sync_label.cget("text"), "◌  Sin cambios")

    def test_edicion_del_usuario_si_marca_como_sucio(self):
        document = self.root / "a.md"
        document.write_text("hola", encoding="utf-8")
        self.app.load_document(document)
        self._settle()

        self.app.editor.insert("end", " escrito por el usuario")
        self._settle()

        self.assertTrue(self.app.session.dirty)
        self.assertIn("Cambios sin guardar", self.app.sync_label.cget("text"))

    def test_cambiar_documento_cambia_a_la_conversacion_del_nuevo_articulo(self):
        """La conversación es por documento: cambiar de artículo no arrastra la anterior."""
        from tukul_core.models import ChatMessage

        a = self.root / "a.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        b = self.root / "b.md"
        b.write_text("TEXTO DE B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        sesion_a = self.app.session
        self.app.session.conversation.append(ChatMessage("user", "hablo del artículo A"))
        self.app.append("Tú", "hablo del artículo A")

        self.app.load_document(b)
        self._settle()

        self.assertIsNot(self.app.session, sesion_a, "Debe ser una ArticleSession nueva")
        self.assertEqual(
            self.app.session.conversation,
            [],
            "B nunca tuvo conversación propia: debe abrir vacía, no heredar la de A",
        )
        self.assertEqual(self.app.session.document_path, b.resolve())
        self.assertNotIn("artículo A", self.app.history.get("1.0", "end-1c"))

        # A conserva su turno: al volver a A (dentro de la misma corrida), se restaura.
        self.app.load_document(a)
        self._settle()
        self.assertEqual(
            [message.content for message in self.app.session.conversation],
            ["hablo del artículo A"],
        )
        self.assertIn("artículo A", self.app.history.get("1.0", "end-1c"))

    def test_abrir_un_documento_ilegible_no_toca_la_sesion(self):
        a = self.root / "a.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        self.app.load_document(a)
        self._settle()
        sesion_a = self.app.session

        with patch.object(TukulApp, "show_error"):
            ok = self.app.load_document(self.root / "no-existe.md")

        self.assertFalse(ok)
        self.assertIs(self.app.session, sesion_a, "Un fallo no debe dejar sesión a medias")
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO DE A")

    def test_la_etiqueta_del_boton_sigue_al_ambito_de_revision(self):
        a = self.root / "a.md"
        a.write_text("primera frase. segunda frase.", encoding="utf-8")
        self.app.load_document(a)
        self._settle()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar artículo")

        self.app.editor.tag_add("sel", "1.0", "1.14")
        self.app.update_context()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar selección")

        self.app.editor.tag_remove("sel", "1.0", "end")
        self.app.update_context()
        self.assertEqual(self.app.review_button.cget("text"), "Revisar artículo")


class TestEscrituraAtomica(unittest.TestCase):
    def test_preserva_los_permisos_del_destino(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "articulo.md"
            target.write_text("original", encoding="utf-8")
            os.chmod(target, 0o644)

            storage.atomic_write(target, "nuevo contenido")

            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            self.assertEqual(target.read_text(encoding="utf-8"), "nuevo contenido")

    def test_archivo_nuevo_no_hereda_permisos_laxos(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nuevo.md"
            storage.atomic_write(target, "x")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


class TestRutasDeProyecto(unittest.TestCase):
    def test_proyecto_fuera_del_arbol_del_articulo_explica_la_restriccion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "art.md"
            document.write_text("x", encoding="utf-8")
            (root / "proyectos").mkdir()
            session = ArticleSession(document_path=document, article="x")

            with self.assertRaises(ValueError) as ctx:
                storage.save_project(session, root / "proyectos" / "p.tukul.json")

            self.assertIn("carpeta del artículo", str(ctx.exception))
            self.assertNotIn("subpath", str(ctx.exception))


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestAprobacionDeContexto(unittest.TestCase):
    """La huella de aprobación no debe cambiar entre mensajes de la misma sesión."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "notas.md").write_text("seguridad y contexto", encoding="utf-8")
        config = self.root / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\nendpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "TEST_KEY_AUDITORIA"\n',
            encoding="utf-8",
        )
        os.environ["TEST_KEY_AUDITORIA"] = "clave"
        self.app = TukulApp(config)
        # confirm_and_send() lanza un hilo daemon real hacia self.app.llm.
        # Sin mock, cada _enviar() dispara una petición HTTP genuina contra un
        # endpoint que no resuelve en este entorno, con reintentos y backoff
        # que sobreviven al test y pueden abortar uno completamente distinto.
        # El parche queda activo hasta tearDown, así que no importa cuándo el
        # hilo llegue a ejecutarlo.
        parche_llm = patch.object(self.app.llm, "stream_response", return_value=None)
        parche_llm.start()
        self.addCleanup(parche_llm.stop)

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()
        os.environ.pop("TEST_KEY_AUDITORIA", None)

    def _enviar(self, mensaje: str) -> None:
        """Ejecuta confirm_and_send con un paquete de contexto fijo.

        Si el contexto ya estaba aprobado, `confirm_and_send` lanza el hilo de
        una: `_envio_previo` se fija ANTES de la llamada para que
        `_aceptar_si_pregunta` (que se llama después, con o sin aprobación de
        por medio) sepa qué `call_count` esperar.
        """
        self.app.generation_counter += 1
        request_id = self.app.generation_counter
        self.app.request_types[request_id] = "normal"
        self._envio_previo = self.app.llm.stream_response.call_count
        self.app.confirm_and_send(
            request_id, mensaje, "artículo", "ARCHIVO LOCAL: notas.md\n---\nseguridad",
            ["notas.md"], threading.Event(),
        )

    def _aceptar_si_pregunta(self) -> bool:
        """Acepta la confirmación en línea si apareció. Devuelve si preguntó.

        En ambos caminos (aprobación nueva vía botón, o contexto ya aprobado
        dentro de `confirm_and_send`) el hilo de envío ya se lanzó al volver
        de aquí; solo falta esperar a que realmente llegue a ejecutarse antes
        de que el test termine y arrastre esa espera a otro test distinto.

        `winfo_ismapped()` refleja el resultado de `pack()` solo después de que
        el gestor de geometría procesó la solicitud: un único `update()` no
        siempre alcanza si el servidor X tarda en confirmarlo (visto de forma
        intermitente bajo Xvfb con la suite corriendo bajo `--cov`). Se
        reintenta brevemente en vez de asumir que un solo ciclo basta.
        """
        limite = time.monotonic() + 1.0
        self.app.update()
        while not self.app.panel_asistente.barra_aprobacion.winfo_ismapped() and time.monotonic() < limite:
            time.sleep(0.01)
            self.app.update()
        pregunto = False
        if self.app.panel_asistente.barra_aprobacion.winfo_ismapped():
            self.app.panel_asistente.boton_aprobar.invoke()
            self.app.update()
            pregunto = True
        _esperar_hilo_de_envio(self.app, self._envio_previo)
        return pregunto

    def test_el_segundo_mensaje_no_vuelve_a_pedir_confirmacion(self):
        self._enviar("primer mensaje")
        self.assertTrue(self._aceptar_si_pregunta(), "El primer envío sí debe confirmarse")

        self._enviar("segundo mensaje")
        self.assertFalse(self._aceptar_si_pregunta(),
                         "Mismo paquete local: no debe reconfirmarse en cada mensaje")
        self._enviar("tercer mensaje")
        self.assertFalse(self._aceptar_si_pregunta())

    def test_un_paquete_distinto_si_vuelve_a_confirmarse(self):
        self._enviar("primer mensaje")
        self.assertTrue(self._aceptar_si_pregunta())

        self.app.generation_counter += 1
        rid = self.app.generation_counter
        self.app.request_types[rid] = "normal"
        self._envio_previo = self.app.llm.stream_response.call_count
        self.app.confirm_and_send(
            rid, "otro", "artículo", "ARCHIVO LOCAL: notas.md\n---\nCONTENIDO NUEVO",
            ["notas.md"], threading.Event(),
        )
        self.assertTrue(self._aceptar_si_pregunta(),
                        "Otro paquete de contexto sí debe reconfirmarse")


class TestSeguridadDelEndpoint(unittest.TestCase):
    def test_acepta_https(self):
        self.assertEqual(
            validate_endpoint("https://api.deepseek.com/chat/completions"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_acepta_http_solo_en_loopback(self):
        validate_endpoint("http://localhost:11434/v1/chat/completions")
        validate_endpoint("http://127.0.0.1:11434/v1/chat/completions")

    def test_rechaza_http_remoto(self):
        with self.assertRaises(LlmError) as ctx:
            validate_endpoint("http://api-remoto.example/v1/chat/completions")
        self.assertIn("https", str(ctx.exception))

    def test_rechaza_esquemas_no_http(self):
        for endpoint in ("file:///etc/passwd", "ftp://host/x", "no-es-una-url"):
            with self.assertRaises(LlmError):
                validate_endpoint(endpoint)

    def test_la_peticion_no_se_construye_con_endpoint_inseguro(self):
        profile = LlmProfile(
            provider="openai_compatible",
            endpoint="http://exfiltra.example/v1/chat/completions",
            model="m",
        )
        with self.assertRaises(LlmError):
            LLMClient()._request(profile, "SECRETO", "hola", stream=False)


class TestLecturaSSEAcotada(unittest.TestCase):
    def test_readline_recibe_un_tope_de_bytes(self):
        from tukul_core.llm import MAX_SSE_LINE_BYTES

        recibidos = []

        class Response:
            def readline(self, limit=-1):
                recibidos.append(limit)
                return b"" if len(recibidos) > 1 else b'data: {"choices":[{"delta":{"content":"x"}}]}\n'

        lineas = list(LLMClient._iter_lines(Response()))

        self.assertEqual(len(lineas), 1)
        self.assertEqual(set(recibidos), {MAX_SSE_LINE_BYTES})

    def test_cae_a_iteracion_si_no_hay_readline(self):
        class Response:
            def __iter__(self):
                return iter((b"data: uno\n", b"data: dos\n"))

        self.assertEqual(len(list(LLMClient._iter_lines(Response()))), 2)


class TestNoRedireccionDeCredenciales(unittest.TestCase):
    """Alta: urlopen sigue 3xx conservando Authorization/x-api-key/x-goog-api-key.

    Un endpoint comprometido, mal configurado o controlado por un atacante
    podría redirigir a otro origen y robar la API key. El cliente debe fallar
    ante el 3xx sin contactar jamás con el destino redirigido.
    """

    def test_el_handler_de_redireccion_jamas_devuelve_un_seguimiento(self):
        from tukul_core.http_safety import _NoRedirectHandler

        handler = _NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                object(), None, 302, "Moved",
                {"Location": "https://otro-origen.example/x"},
                "https://otro-origen.example/x",
            )
        )

    def test_un_302_real_no_reenvia_la_api_key_al_origen_redirigido(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        recibido: dict[str, str] = {}

        class Destino(BaseHTTPRequestHandler):
            def _registrar(self):
                recibido["authorization"] = str(self.headers.get("Authorization"))
                recibido["x-api-key"] = str(self.headers.get("x-api-key"))
                recibido["x-goog-api-key"] = str(self.headers.get("x-goog-api-key"))

            def do_POST(self):
                self._registrar()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')

            def do_GET(self):
                # Si la corrección se revierte, el 302 se sigue como GET (con la
                # cabecera de autenticación copiada) y la key llega hasta aquí.
                self._registrar()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')

            def log_message(self, *_args):
                pass

        destino = ThreadingHTTPServer(("127.0.0.1", 0), Destino)
        hilo_destino = threading.Thread(target=destino.serve_forever, daemon=True)
        hilo_destino.start()

        class Redirige(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{destino.server_port}/v1/chat/completions",
                )
                self.end_headers()

            def log_message(self, *_args):
                pass

        redirige = ThreadingHTTPServer(("127.0.0.1", 0), Redirige)
        hilo_redirige = threading.Thread(target=redirige.serve_forever, daemon=True)
        hilo_redirige.start()

        try:
            profile = LlmProfile(
                provider="openai_compatible",
                endpoint=f"http://127.0.0.1:{redirige.server_port}/v1/chat/completions",
                model="m",
            )
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(profile, "KEY-SECRETA-DE-PRUEBA", "hola")
            self.assertIn("302", str(ctx.exception))
            self.assertEqual(
                recibido, {}, "El destino de la redirección no debe recibir la API key"
            )
        finally:
            redirige.shutdown()
            destino.shutdown()
            redirige.server_close()
            destino.server_close()


class TestRespuestaCompletaAcotada(unittest.TestCase):
    """Media: complete() no debe cargar en memoria un cuerpo arbitrariamente grande."""

    def _perfil(self):
        return LlmProfile(provider="openai_compatible", endpoint="https://example.invalid", model="m")

    def test_content_length_gigante_se_rechaza_sin_leer_el_cuerpo(self):
        class Response:
            def __init__(self):
                self.headers = {"Content-Length": "999999999"}

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def read(self, *_args):
                raise AssertionError("No debe leerse un cuerpo ya predeclarado como excesivo")

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=Response()):
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(self._perfil(), "key", "mensaje")
        self.assertIn("mayor de lo esperado", str(ctx.exception))

    def test_la_lectura_incremental_aborta_al_superar_el_techo(self):
        from tukul_core.llm import BYTES_PER_OUTPUT_TOKEN, MAX_BODY_OVERHEAD_BYTES

        max_bytes = MAX_BODY_OVERHEAD_BYTES + BYTES_PER_OUTPUT_TOKEN
        perfil = LlmProfile(
            provider="openai_compatible", endpoint="https://example.invalid",
            model="m", max_output_tokens=1,
        )

        class Response:
            def __init__(self, cuerpo: bytes):
                self._buffer = io.BytesIO(cuerpo)

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def read(self, amt: int = -1):
                return self._buffer.read(amt)

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open",
                   return_value=Response(b"x" * (max_bytes + 4096))):
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(perfil, "key", "mensaje")
        self.assertIn("mayor de lo esperado", str(ctx.exception))

    def test_el_fallback_iterable_aborta_antes_de_acumular_el_cuerpo_entero(self):
        from tukul_core.llm import BYTES_PER_OUTPUT_TOKEN, MAX_BODY_OVERHEAD_BYTES

        max_bytes = MAX_BODY_OVERHEAD_BYTES + BYTES_PER_OUTPUT_TOKEN
        perfil = LlmProfile(
            provider="openai_compatible", endpoint="https://example.invalid",
            model="m", max_output_tokens=1,
        )

        class Response:
            def __init__(self):
                self.headers = {}

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def __iter__(self):
                yield b"x" * max_bytes
                yield b"x"
                raise AssertionError("No deben consumirse fragmentos tras exceder el techo")

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=Response()):
            with self.assertRaises(LlmError) as ctx:
                LLMClient().complete(perfil, "key", "mensaje")
        self.assertIn("mayor de lo esperado", str(ctx.exception))

    def test_respuesta_dentro_del_techo_se_acepta(self):
        perfil = self._perfil()
        cuerpo = b'{"choices":[{"message":{"content":"ok"}}]}'

        class Response:
            def __init__(self):
                self.headers = {"Content-Length": str(len(cuerpo))}
                self._buffer = io.BytesIO(cuerpo)

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def read(self, amt: int = -1):
                return self._buffer.read(amt)

        with patch("tukul_core.llm._OPENER_NO_REDIRECT.open", return_value=Response()):
            result = LLMClient().complete(perfil, "key", "mensaje")
        self.assertEqual(result.content, "ok")


class TestCredenciales(unittest.TestCase):
    def test_delete_key_es_silenciosa_sin_llavero(self):
        original = storage.keyring
        storage.keyring = None
        try:
            storage.delete_key("cualquiera")  # no debe lanzar
        finally:
            storage.keyring = original

    def test_delete_key_revoca_en_el_llavero(self):
        original = storage.keyring
        storage.keyring = Mock()
        try:
            storage.delete_key("perfil")
            storage.keyring.delete_password.assert_called_once_with(
                "tukul", "perfil"
            )
        finally:
            storage.keyring = original

    def test_delete_key_propaga_fallos_reales_del_llavero(self):
        original = storage.keyring
        storage.keyring = Mock()
        storage.keyring.delete_password.side_effect = OSError("backend caído")
        try:
            with self.assertRaises(OSError):
                storage.delete_key("perfil")
        finally:
            storage.keyring = original


class TestPerfilesInvalidos(unittest.TestCase):
    def test_perfil_corrupto_se_ignora_dejando_rastro(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                '[llm]\nactive_profile = "malo"\n\n'
                '[profiles.malo]\nprovider = "openai_compatible"\n'
                'endpoint = "https://x/y"\nmodel = "m"\ntemperature = 9.0\n',
                encoding="utf-8",
            )

            with patch.object(storage.logger, "warning") as warn:
                profiles, active = storage.load_profiles(config)

            self.assertNotIn("malo", profiles)
            self.assertEqual(active, "default")
            self.assertTrue(
                any("malo" in str(call) for call in warn.call_args_list),
                "El perfil descartado debe aparecer en el log",
            )


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestDeshacerRevisionEntreDocumentos(unittest.TestCase):
    """El "antes" de una sugerencia pertenece a un documento concreto."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_deshacer_no_vuelca_el_articulo_anterior_sobre_el_nuevo(self):
        a = self.root / "articulo_A.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        b = self.root / "articulo_B.md"
        b.write_text("TEXTO DE B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        self.app.snapshot_for_undo(self.app.editor.get("1.0", "end-1c"))

        self.app.load_document(b)
        self._settle()
        self.app.undo_review()
        self._settle()

        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO DE B")
        self.assertFalse(self.app.session.dirty, "B no debe quedar sucio con texto de A")

    def test_deshacer_sigue_funcionando_dentro_del_mismo_documento(self):
        a = self.root / "articulo_A.md"
        a.write_text("TEXTO ORIGINAL", encoding="utf-8")
        self.app.load_document(a)
        self._settle()

        self.app.snapshot_for_undo("TEXTO ORIGINAL")
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", "TEXTO REVISADO")
        self._settle()
        self.app.undo_review()
        self._settle()

        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO ORIGINAL")


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestDialogoDeRevisionAnclado(unittest.TestCase):
    """Los hallazgos pertenecen al artículo sobre el que se calcularon."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")
        self.hallazgo = {
            "category": "gramática", "severity": "alta", "original": "floja",
            "suggestion": "POCO SÓLIDA", "reason": "registro",
        }

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _pulsar(self, dialog, etiqueta):
        from tkinter import ttk as _ttk

        botones = []
        def recorrer(widget):
            for hijo in widget.winfo_children():
                if isinstance(hijo, _ttk.Button):
                    botones.append(hijo)
                recorrer(hijo)
        recorrer(dialog)
        for boton in botones:
            if boton.cget("text") == etiqueta:
                boton.invoke()
                return True
        return False

    def test_no_aplica_hallazgos_de_otro_articulo(self):
        a = self.root / "A.md"
        a.write_text("La introducción es floja.", encoding="utf-8")
        b = self.root / "B.md"
        b.write_text("Otro artículo con redacción floja también.", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        self.app.show_findings([dict(self.hallazgo)])
        self._settle()
        dialogo = self.app.review_dialogs[0]

        self.app.load_document(b)
        self._settle()
        contenido_b = self.app.editor.get("1.0", "end-1c")

        if dialogo.winfo_exists():
            with patch("tukul_ui.dialogs.messagebox.showinfo"):
                self._pulsar(dialogo, "Aplicar")
            self._settle()

        self.assertEqual(self.app.editor.get("1.0", "end-1c"), contenido_b)
        self.assertFalse(self.app.session.dirty, "B no debe ensuciarse con una sugerencia de A")

    def test_solo_queda_un_dialogo_de_revision_abierto(self):
        a = self.root / "A.md"
        a.write_text("La introducción es floja.", encoding="utf-8")
        self.app.load_document(a)
        self._settle()

        for _ in range(4):
            self.app.show_findings([dict(self.hallazgo)])
            self._settle()

        vivos = [d for d in self.app.review_dialogs if d.winfo_exists()]
        self.assertEqual(len(vivos), 1, "Cada revisión debe reemplazar la anterior")

    def test_dentro_del_mismo_articulo_la_sugerencia_si_se_aplica(self):
        a = self.root / "A.md"
        a.write_text("La introducción es floja.", encoding="utf-8")
        self.app.load_document(a)
        self._settle()

        self.app.show_findings([dict(self.hallazgo)])
        self._settle()
        with patch("tukul_ui.dialogs.messagebox.showinfo"):
            self._pulsar(self.app.review_dialogs[0], "Aplicar")
        self._settle()

        self.assertIn("POCO SÓLIDA", self.app.editor.get("1.0", "end-1c"))
        self.assertTrue(self.app.session.dirty)


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestAmbitoDelDocumento(unittest.TestCase):
    """Vigilancia estructural del patrón que produjo A-25, A-34 y A-35.

    Este test no comprueba un campo concreto: recorre TODOS los campos de
    DocumentScope. Si alguien añade uno nuevo y la renovación de ámbito deja de
    cubrirlo, esta prueba falla sin que nadie tenga que acordarse de ampliarla.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    @staticmethod
    def _valor_sucio(campo):
        """Un valor distinto del defecto, sea cual sea el tipo del campo."""
        if campo.name == "document_path":
            return Path("/documento/anterior.md")
        muestras = {str: "residuo del documento anterior", list: ["residuo.md"], dict: {"residuo": 1}, bool: True, int: 99}
        for tipo, valor in muestras.items():
            if campo.type in (tipo, tipo.__name__) or tipo.__name__ in str(campo.type):
                return valor
        return "residuo del documento anterior"

    def test_todo_campo_del_ambito_se_renueva_al_cambiar_de_documento(self):
        import dataclasses

        a = self.root / "a.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        b = self.root / "b.md"
        b.write_text("TEXTO DE B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()

        campos = dataclasses.fields(DocumentScope)
        self.assertGreater(len(campos), 1, "DocumentScope debe tener campos que vigilar")
        for campo in campos:
            setattr(self.app.scope, campo.name, self._valor_sucio(campo))

        self.app.load_document(b)
        self._settle()

        limpio = DocumentScope(document_path=b.resolve())
        for campo in campos:
            self.assertEqual(
                getattr(self.app.scope, campo.name),
                getattr(limpio, campo.name),
                f"El campo '{campo.name}' sobrevivió al cambio de documento. "
                f"El ámbito debe reemplazarse entero en _enter_document_scope.",
            )

    def test_el_ambito_es_un_objeto_nuevo_no_el_mismo_mutado(self):
        a = self.root / "a.md"
        a.write_text("A", encoding="utf-8")
        b = self.root / "b.md"
        b.write_text("B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        ambito_a = self.app.scope

        self.app.load_document(b)
        self._settle()

        self.assertIsNot(self.app.scope, ambito_a, "Reemplazar, no limpiar campo a campo")
        self.assertTrue(self.app.scope.owns(b.resolve()))
        self.assertFalse(self.app.scope.owns(a.resolve()))

    def test_guardar_como_conserva_el_ambito_y_sigue_a_la_ruta_nueva(self):
        a = self.root / "a.md"
        a.write_text("TEXTO ORIGINAL", encoding="utf-8")
        self.app.load_document(a)
        self._settle()
        self.app.snapshot_for_undo("TEXTO ORIGINAL")
        destino = self.root / "renombrado.md"

        with patch("tukul_ui.app.filedialog.asksaveasfilename", return_value=str(destino)):
            self.assertTrue(self.app.save_document(save_as=True))
        self._settle()

        # Renombrar no es cambiar de artículo: el deshacer debe seguir vivo.
        self.assertTrue(self.app.scope.owns(destino.resolve()))
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", "TEXTO MODIFICADO")
        self.app.undo_review()
        self._settle()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO ORIGINAL")


class TestSaludDeLaInstalacion(unittest.TestCase):
    def test_instalacion_nueva_tiene_avisos_pero_no_errores(self):
        from tukul_core import health

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(storage, "CONFIG_PATH", Path(directory) / "nada" / "config.toml"):
                status = health.check_health()

        self.assertFalse(status.is_healthy, "Sin perfiles hay avisos")
        self.assertFalse(status.has_errors, "…pero nada roto: --health debe salir con 0")

    def test_directorio_de_config_no_escribible_es_error(self):
        from tukul_core.health import ComponentStatus, check_health

        with tempfile.TemporaryDirectory() as directory:
            solo_lectura = Path(directory) / "cfg"
            solo_lectura.mkdir()
            os.chmod(solo_lectura, 0o500)
            try:
                with patch.object(storage, "CONFIG_PATH", solo_lectura / "config.toml"):
                    status = check_health()
                self.assertEqual(status.components["storage"][0], ComponentStatus.ERROR)
                self.assertTrue(status.has_errors)
            finally:
                os.chmod(solo_lectura, 0o700)

    def test_check_health_diagnostica_el_config_indicado_no_el_por_defecto(self):
        from tukul_core.health import check_health

        with tempfile.TemporaryDirectory() as directory:
            propio = Path(directory) / "propio.toml"
            perfiles = "\n".join(
                f'[profiles.p{i}]\nprovider = "openai_compatible"\n'
                f'endpoint = "https://x.example/v1/chat/completions"\nmodel = "m{i}"'
                for i in range(3)
            )
            propio.write_text(f'[llm]\nactive_profile = "p0"\n\n{perfiles}\n', encoding="utf-8")

            status = check_health(propio)

            self.assertEqual(status.config_path, str(propio))
            self.assertIn("3 perfil(es) habilitado(s)", status.components["llm"][1])

    def test_status_string_declara_el_archivo_inspeccionado(self):
        from tukul_core.health import check_health, status_string

        with tempfile.TemporaryDirectory() as directory:
            propio = Path(directory) / "propio.toml"
            propio.write_text("[llm]\n", encoding="utf-8")

            texto = status_string(check_health(propio))

            self.assertIn(str(propio), texto)

    def test_la_cli_pasa_config_al_diagnostico(self):
        import subprocess

        raiz = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as directory:
            propio = Path(directory) / "cli.toml"
            perfiles = "\n".join(
                f'[profiles.p{i}]\nprovider = "openai_compatible"\n'
                f'endpoint = "https://x.example/v1/chat/completions"\nmodel = "m{i}"'
                for i in range(2)
            )
            propio.write_text(f'[llm]\nactive_profile = "p0"\n\n{perfiles}\n', encoding="utf-8")

            proceso = subprocess.run(
                [sys.executable, "tukul.py", "--config", str(propio), "--health"],
                cwd=raiz, capture_output=True, text=True, timeout=60,
            )

            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            self.assertIn(str(propio), proceso.stdout)
            self.assertIn("2 perfil(es) habilitado(s)", proceso.stdout)

    def test_check_health_lee_la_configuracion_una_sola_vez(self):
        from tukul_core import health

        with patch.object(storage, "load_profiles", wraps=storage.load_profiles) as leer:
            health.check_health()
        self.assertEqual(leer.call_count, 1, "Se parseaba config.toml dos veces")


class TestLogging(unittest.TestCase):
    def test_health_y_config_validator_usan_el_logger_de_la_app(self):
        from tukul_core import config_validator, health
        from tukul_core.logging_config import LOGGER_NAME

        self.assertEqual(health.logger.name, LOGGER_NAME)
        self.assertEqual(config_validator.logger.name, LOGGER_NAME)
        self.assertTrue(health.logger.handlers, "Sin handlers no llega al log JSON")

    def test_setup_logging_honra_una_ruta_explicita(self):
        from tukul_core.logging_config import setup_logging

        with tempfile.TemporaryDirectory() as directory:
            deseada = Path(directory) / "sub" / "propio.log"
            logger = setup_logging(deseada)
            try:
                efectivas = [
                    Path(h.baseFilename) for h in logger.handlers if hasattr(h, "baseFilename")
                ]
                self.assertIn(deseada, efectivas, "El parámetro log_path se ignoraba")
                self.assertTrue(deseada.exists())
            finally:
                setup_logging(Path(directory) / "descartable.log")

    def test_el_diagnostico_no_declara_sano_un_log_inexistente(self):
        """El chequeo anterior solo comprobaba que logger.debug() no lanzara.

        Con handler de consola presente nunca lanza, así que un destino de log
        imposible (sistema de archivos de solo lectura) se reportaba como «OK».
        """
        import subprocess

        raiz = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as directory:
            hogar = Path(directory) / "hogar"
            hogar.mkdir()
            os.chmod(hogar, 0o500)  # sin permiso de escritura
            try:
                entorno = {**os.environ, "HOME": str(hogar)}
                proceso = subprocess.run(
                    [sys.executable, "tukul.py", "--health"],
                    cwd=raiz, capture_output=True, text=True, timeout=60, env=entorno,
                )
            finally:
                os.chmod(hogar, 0o700)

            self.assertNotIn(
                "logging: ✓", proceso.stdout,
                "El log no pudo crearse; declararlo sano es un falso positivo",
            )
            self.assertIn("logging: ⚠", proceso.stdout)
            self.assertIn("solo consola", proceso.stdout)

    def test_file_logging_status_detecta_un_destino_que_deja_de_escribirse(self):
        from tukul_core.logging_config import file_logging_status, setup_logging

        with tempfile.TemporaryDirectory() as directory:
            destino = Path(directory) / "vivo.log"
            setup_logging(destino)
            try:
                operativo, detalle = file_logging_status()
                self.assertTrue(operativo, detalle)
                self.assertIn(str(destino), detalle)

                # El sistema de archivos puede volverse de solo lectura DESPUÉS
                # del arranque: recordar el error de inicio no bastaría.
                os.chmod(destino, 0o400)
                operativo, detalle = file_logging_status()
                self.assertFalse(operativo)
                self.assertIn("no escribible", detalle)
            finally:
                os.chmod(destino, 0o600)
                setup_logging(Path(directory) / "descartable.log")

    def test_la_rotacion_acota_el_tamano_en_disco(self):
        import logging
        from logging.handlers import RotatingFileHandler

        with tempfile.TemporaryDirectory() as directory:
            destino = Path(directory) / "r.log"
            handler = RotatingFileHandler(destino, maxBytes=512_000, backupCount=2, encoding="utf-8")
            aislado = logging.getLogger("tukul.test.rotacion")
            aislado.propagate = False
            aislado.addHandler(handler)
            aislado.setLevel(logging.INFO)
            try:
                for _ in range(4000):
                    aislado.info("y" * 300)
            finally:
                aislado.removeHandler(handler)
                handler.close()

            familia = list(destino.parent.glob(destino.name + "*"))
            total = sum(f.stat().st_size for f in familia)
            self.assertLessEqual(len(familia), 3, "1 activo + 2 backups")
            self.assertLess(total, 1_600_000, "512KB x 3 es el techo teórico")


class TestKeysDeSesion(unittest.TestCase):
    """Actualizar una key no debe desalojar la de otro perfil."""

    def _holder(self, maximo: int):
        holder = TukulApp.__new__(TukulApp)
        holder.session_keys = {}
        holder._session_keys_max = maximo
        return holder

    def test_actualizar_una_key_existente_no_desaloja_a_nadie(self):
        holder = self._holder(3)
        for name in ("p1", "p2", "p3"):
            holder._add_session_key(name, f"k-{name}")

        holder._add_session_key("p2", "k-p2-nueva")

        self.assertEqual(len(holder.session_keys), 3)
        self.assertEqual(holder.session_keys["p1"], "k-p1")
        self.assertEqual(holder.session_keys["p2"], "k-p2-nueva")

    def test_insertar_una_key_nueva_desaloja_la_menos_reciente(self):
        holder = self._holder(3)
        for name in ("p1", "p2", "p3"):
            holder._add_session_key(name, f"k-{name}")
        holder._add_session_key("p2", "k-p2-nueva")  # p2 pasa a ser la más reciente

        holder._add_session_key("p4", "k-p4")

        self.assertNotIn("p1", holder.session_keys)
        self.assertEqual(set(holder.session_keys), {"p2", "p3", "p4"})


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestAprobacionesDesalojoFIFO(unittest.TestCase):
    def test_al_llenarse_se_desaloja_la_mas_antigua_no_todas(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "notas.md").write_text("seguridad", encoding="utf-8")
        config = root / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\nendpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "TEST_KEY_FIFO"\n',
            encoding="utf-8",
        )
        os.environ["TEST_KEY_FIFO"] = "clave"
        self.addCleanup(lambda: os.environ.pop("TEST_KEY_FIFO", None))
        app = TukulApp(config)
        # Igual que en TestAprobacionDeContexto: confirm_and_send() lanza un
        # hilo real hacia app.llm si no se mockea, con el mismo riesgo de
        # petición HTTP genuina y reintentos que sobreviven al test. Se
        # registra antes que `app.destroy` para que, por orden LIFO de
        # addCleanup, el parche siga activo hasta después de destruir la app.
        parche_llm = patch.object(app.llm, "stream_response", return_value=None)
        parche_llm.start()
        self.addCleanup(parche_llm.stop)
        self.addCleanup(app.destroy)

        # Saturar con 128 aprobaciones previas, la primera identificable.
        primera = (app.profile.endpoint, app.profile.provider, app.profile.model, ("notas.md",), "h-primera")
        app.approved_contexts[primera] = None
        for i in range(127):
            app.approved_contexts[(app.profile.endpoint, app.profile.provider, app.profile.model, ("notas.md",), f"h{i}")] = None

        app.generation_counter += 1
        rid = app.generation_counter
        app.request_types[rid] = "normal"
        desde = app.llm.stream_response.call_count
        app.confirm_and_send(rid, "hola", "art", "paquete nuevo", ["notas.md"], threading.Event())
        app.update()
        app.panel_asistente.boton_aprobar.invoke()   # confirmación en línea, no modal
        app.update()
        _esperar_hilo_de_envio(app, desde)

        self.assertEqual(len(app.approved_contexts), 128, "El tope se mantiene")
        self.assertNotIn(primera, app.approved_contexts, "Se desaloja la más antigua")
        self.assertIn(
            (app.profile.endpoint, app.profile.provider, app.profile.model, ("notas.md",), "h126"),
            app.approved_contexts,
            "Las demás sobreviven: no es un vaciado total",
        )


class TestParserFindingsNoIterable(unittest.TestCase):
    def test_findings_no_lista_se_descarta_sin_recorrerla(self):
        from tukul_core.review import parse_findings

        self.assertEqual(parse_findings('{"findings":"' + "x" * 100_000 + '"}'), [])
        self.assertEqual(parse_findings('{"findings":{"a":1}}'), [])
        self.assertEqual(parse_findings('{"findings":42}'), [])


class TestDocumentManagerEsElDuenoDeLaPersistencia(unittest.TestCase):
    """Los métodos que la app duplicaba deben existir y comportarse."""

    def test_save_project_traduce_el_error_de_ruta(self):
        from tukul_ui.document_manager import DocumentManager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "art.md"
            document.write_text("x", encoding="utf-8")
            (root / "sub").mkdir()

            ok, error = DocumentManager().save_project(
                ArticleSession(document_path=document, article="x"),
                root / "sub" / "p.tukul.json",
            )

            self.assertFalse(ok)
            self.assertIn("carpeta del artículo", error)

    def test_open_project_devuelve_error_si_falta_el_articulo(self):
        import json

        from tukul_ui.document_manager import DocumentManager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "p.tukul.json"
            project.write_text(
                json.dumps({"version": 2, "document": "no-existe.md"}), encoding="utf-8"
            )

            ok, error, _session = DocumentManager().open_project(project)

            self.assertFalse(ok)
            self.assertIn("No existe el artículo", error)


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestGestionDePerfiles(unittest.TestCase):
    """El diálogo de configuración permite crear y borrar perfiles."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        config = self.root / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p1"\n\n'
            '[profiles.p1]\nprovider = "openai_compatible"\n'
            'endpoint = "https://x.example/v1/chat/completions"\n'
            'model = "m1"\napi_key_env = "CLAVE_PERFILES"\n\n'
            '[profiles.p2]\nprovider = "openai_compatible"\n'
            'endpoint = "https://x.example/v1/chat/completions"\n'
            'model = "m2"\napi_key_env = "CLAVE_PERFILES"\n',
            encoding="utf-8",
        )
        os.environ["CLAVE_PERFILES"] = "clave"
        self.addCleanup(lambda: os.environ.pop("CLAVE_PERFILES", None))
        self.app = TukulApp(config)
        self.addCleanup(self.app.destroy)
        self._settle()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _widgets(self):
        from tkinter import ttk

        dialogo = next(w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel")

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        widgets = list(walk(dialogo))
        return dialogo, widgets

    def test_el_dialogo_lista_todos_los_perfiles(self):
        from tkinter import ttk

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        combo = next(
            w for w in widgets
            if isinstance(w, ttk.Combobox) and w.cget("values") == ("default", "p1", "p2")
        )
        self.assertEqual(list(combo.cget("values")), ["default", "p1", "p2"])

    def test_borrar_un_perfil_lo_quita_y_guardar_actualiza_la_app(self):
        from tkinter import ttk

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}

        with patch("tukul_ui.dialogs.messagebox.askyesno", return_value=True):
            buttons["Borrar"].invoke()  # borra el activo «p1»
        self._settle()

        with patch("tukul_ui.dialogs.messagebox.showinfo") as info, \
                patch("tukul_ui.dialogs.messagebox.showerror") as error:
            buttons["Guardar"].invoke()
        self._settle()

        self.assertNotIn("p1", self.app.profiles, "El perfil borrado ya no debe existir")
        self.assertIn("p2", self.app.profiles)
        error.assert_not_called()
        info.assert_called_once()

    def test_guardar_sin_llavero_no_deja_el_dialogo_colgado(self):
        """Sin llavero de sistema (CI) el guardado no abre un error modal.

        `save()` persiste primero y luego la credencial; si el backend falla,
        mostraba `showerror`, que en una sesión sin interacción espera un clic
        para siempre. El perfil sí se guarda: la key queda solo en sesión, que
        es el comportamiento documentado sin llavero.
        """
        from tkinter import ttk

        from tukul_core import storage

        original = storage.keyring
        storage.keyring = None
        self.addCleanup(lambda: setattr(storage, "keyring", original))

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}

        with patch("tukul_ui.dialogs.messagebox.showinfo"), \
                patch("tukul_ui.dialogs.messagebox.showerror") as error:
            buttons["Guardar"].invoke()
        self._settle()

        error.assert_not_called()
        self.assertIn("p1", self.app.profiles, "Sin llavero el perfil se guarda igual")

    def test_nuevo_perfil_se_crea_y_pasa_a_ser_activo(self):
        from tkinter import ttk

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}

        with patch("tukul_ui.dialogs.simpledialog.askstring", return_value="p3"):
            buttons["Nuevo"].invoke()
        self._settle()

        with patch("tukul_ui.dialogs.messagebox.showinfo"):
            buttons["Guardar"].invoke()
        self._settle()

        self.assertIn("p3", self.app.profiles, "El perfil nuevo debe guardarse")
        self.assertEqual(self.app.active_profile, "p3", "El perfil nuevo pasa a ser el activo")


if __name__ == "__main__":
    unittest.main()
