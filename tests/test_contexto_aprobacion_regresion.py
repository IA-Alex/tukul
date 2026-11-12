"""Regresiones de la auditoría estructural — aprobación de contexto.

Dividido de `test_auditoria_regresion.py` (1.544 líneas, 22 clases mezclando
dominios) por dominio. Cada prueba ejecuta código de producción: si se revierte
la corrección, la prueba falla.
"""
import io
import os
import queue
import stat
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from _regresion_helpers import (
    HAS_DISPLAY,
    _display_available,
    _esperar_hilo_de_envio,
    _headless_app,
)

from tukul_core import storage
from tukul_core.llm import LLMClient, LlmError, validate_endpoint
from tukul_core.models import ArticleSession, LlmProfile
from tukul_ui.app import TukulApp
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import EstadoUI


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
