"""Caminos de riesgo de `TukulApp` que la suite no ejecutaba.

Cada prueba fija una rama que el usuario puede alcanzar y que, si se rompe,
deja la ventana en un estado que no se recupera sola: cierre con petición viva,
recuperación de respaldo tras un cierre abrupto, recientes desaparecidos,
estado de interfaz corrupto, validación de tamaño antes de enviar y el
diagnóstico de errores no controlados.

Los identificadores son de líneas de `tukul_ui/app.py` en el momento de
escribirlas; el nombre de la prueba se mantiene aunque la línea se mueva.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core import storage
from tukul_ui import app as modulo_app
from tukul_ui.app import TukulApp
from tukul_ui.estado import EstadoUI

CLAVE = "CLAVE_PRUEBA_APP_RAMAS"
CONFIG = (
    '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
    'provider = "openai_compatible"\n'
    'endpoint = "https://api.example.com/v1/chat/completions"\n'
    'model = "m"\napi_key_env = "' + CLAVE + '"\n'
)


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class _BaseApp(unittest.TestCase):
    """Ventana real sobre un config temporal; sin red (el LLM va parcheado)."""

    config_texto = CONFIG

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.config = self.raiz / "config.toml"
        self.config.write_text(self.config_texto, encoding="utf-8")
        os.environ[CLAVE] = "clave"
        self.documento = self.raiz / "articulo.md"
        self.documento.write_text("La introducción es floja y conviene recortarla.",
                                  encoding="utf-8")
        self.app = TukulApp(self.config)
        self.app.load_document(self.documento)
        self._asentar()

    def tearDown(self):
        # Un worker lanzado en la prueba (p. ej. el pipeline de ideas) puede
        # seguir vivo con la ventana ya cerrada. Se le da su margen ANTES de
        # destruir: si sobrevive y luego toca Tcl, CPython aborta el proceso y
        # el fallo aparece, engañosamente, en un test posterior.
        # Un objeto Tk liberado desde un hilo ajeno aborta el intérprete en
        # CPython 3.13 (`Variable.__del__` → «main thread is not in main
        # loop»). Se recolecta aquí, en el hilo principal y sin workers vivos,
        # para que esa basura no caiga en el worker de un test posterior.
        # Algunas pruebas ya cerraron la ventana: destruir de nuevo levantaría.
        try:
            self.app.destroy()
        except tk.TclError:
            pass
        self.directorio.cleanup()
        os.environ.pop(CLAVE, None)

    def _asentar(self, veces: int = 5):
        for _ in range(veces):
            self.app.update()
            self.app.update_idletasks()


class TestCierreConPeticionViva(_BaseApp):
    """`close()` cancela, espera los hilos con tope y persiste antes de destruir."""

    def test_close_cancela_el_evento_de_la_peticion_viva(self):
        """Con una petición viva: se marca SU evento antes de destruir la ventana.

        `_cancel_active_request` NO se parchea: es justo lo que este cierre
        debe ejecutar. Un doble que la sustituía dejaba la petición sin
        cancelar y el worker sobrevivía a la ventana (visto como aborto del
        intérprete en la suite completa).
        """
        import threading

        evento = threading.Event()
        self.app.session.request_active = True
        self.app.cancel_event = evento
        with patch.object(modulo_app.WorkerThreads, "vivos", return_value=[]), \
                patch.object(TukulApp, "_guardar_estado_ui", autospec=True) as guardar:
            self.app.close()
        self.assertTrue(evento.is_set(), "Cerrar debe cancelar la petición viva")
        guardar.assert_called_once()
        self.assertTrue(self.app.closing)
        self.assertFalse(self.app.session.request_active)

    def test_destroy_no_espera_si_no_hay_hilos(self):
        """El caso normal del cierre: nada vivo, el tope no se aplica."""
        self.assertEqual(modulo_app.WorkerThreads.esperar(0.0), [])
        inicio = time.monotonic()
        self.app.destroy()
        self.assertLess(time.monotonic() - inicio, 1.0)

    def test_destroy_avisa_cuando_un_hilo_de_peticion_no_termina(self):
        """Un worker colgado no bloquea el cierre, pero deja constancia.

        Es la rama de aviso de `_esperar_hilos_de_peticion`: sin ella, un hilo
        que sobrevive a la ventana se ejecutaría contra Tcl desde otro hilo
        sin que nadie lo supiera.
        """
        self.app.closing = True
        with patch.object(modulo_app.WorkerThreads, "esperar", return_value=[object()]), \
                patch.object(modulo_app.logger, "warning") as aviso:
            self.app._esperar_hilos_de_peticion()
        aviso.assert_called_once()
        self.assertIn("hilo(s)", aviso.call_args[0][0])

    def test_destroy_tolera_after_ya_disparados(self):
        """`after_cancel` sobre un id caducado lanza TclError: el cierre sigue."""
        self.app.closing = True
        with patch.object(self.app, "after_cancel", side_effect=tk.TclError("bad id")):
            self.app.destroy()


class TestEsperaDeKeyring(_BaseApp):
    """El tope del llavero es total, no por lectura: un backend colgado no cuelga el cierre."""

    def test_sin_lecturas_no_espera(self):
        self.app._llaves_en_curso.clear()
        inicio = time.monotonic()
        self.app._esperar_hilos_de_keyring(timeout=5.0)
        self.assertLess(time.monotonic() - inicio, 0.5)

    def test_un_llavero_colgado_agota_el_tope_y_sigue(self):
        import threading

        pendiente = threading.Event()
        self.app._llaves_en_curso["p"] = pendiente
        inicio = time.monotonic()
        self.app._esperar_hilos_de_keyring(timeout=0.05)
        transcurrido = time.monotonic() - inicio
        pendiente.set()
        self.assertLess(transcurrido, 1.0, "El tope debe cortar la espera")
        self.assertIn("p", self.app._llaves_en_curso)


class TestRecuperacionDeRespaldo(_BaseApp):
    """Tras un cierre abrupto, abrir el documento ofrece el respaldo una sola vez."""

    def _reabrir(self, escribir_respaldo: str | None):
        from tukul_core import autosave

        with patch.object(autosave, "AUTOSAVE_DIR", self.raiz / "autosave"):
            if escribir_respaldo is not None:
                autosave.write_autosave(self.documento, escribir_respaldo)
            self.app.load_document(self.documento)
            self._asentar()
            restante = autosave.read_autosave(self.documento)
        return restante

    def test_aceptar_restaura_el_respaldo_y_lo_borra(self):
        with patch.object(modulo_app.messagebox, "askyesno", return_value=True) as preguntar:
            restante = self._reabrir("TEXTO SIN GUARDAR")
        preguntar.assert_called_once()
        self.assertIn("Recuperar respaldo", preguntar.call_args[0][0])
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO SIN GUARDAR")
        self.assertIsNone(restante, "Resuelta la decisión, el respaldo no debe resucitar")

    def test_rechazar_conserva_el_disco_y_tambien_lo_borra(self):
        with patch.object(modulo_app.messagebox, "askyesno", return_value=False):
            restante = self._reabrir("TEXTO SIN GUARDAR")
        self.assertEqual(self.app.editor.get("1.0", "end-1c"),
                         "La introducción es floja y conviene recortarla.")
        self.assertIsNone(restante)

    def test_sin_respaldo_no_pregunta(self):
        with patch.object(modulo_app.messagebox, "askyesno", return_value=True) as preguntar:
            self._reabrir(None)
        preguntar.assert_not_called()


class TestAutosave(_BaseApp):
    """El respaldo se escribe mientras el documento está sucio, y se detiene al cerrar."""

    def _autosave_aislado(self):
        from tukul_core import autosave
        return patch.object(autosave, "AUTOSAVE_DIR", self.raiz / "autosave")

    def test_una_edicion_sucia_escribe_el_respaldo_y_rearma(self):
        from tukul_core import autosave

        with self._autosave_aislado():
            self.app.session.dirty = True
            self.app.editor.insert("end", " otra frase")
            self.app._write_autosave()
            guardado = autosave.read_autosave(self.documento)
        self.assertIn("otra frase", guardado)
        self.assertIsNotNone(self.app.autosave_after, "Si sigue sucio, se rearma")

    def test_cerrando_no_se_escribe_nada(self):
        from tukul_core import autosave

        with self._autosave_aislado():
            autosave.clear_autosave(self.documento)
            self.app.session.dirty = True
            self.app.closing = True
            self.app._write_autosave()
            self.assertIsNone(autosave.read_autosave(self.documento))
        self.assertIsNone(self.app.autosave_after)

    def test_un_documento_limpio_no_escribe_respaldo(self):
        from tukul_core import autosave

        with self._autosave_aislado():
            autosave.clear_autosave(self.documento)
            self.app.session.dirty = False
            self.app._write_autosave()
            self.assertIsNone(autosave.read_autosave(self.documento))

    def test_clear_current_autosave_cancela_el_temporizador(self):
        self.app._schedule_autosave()
        self.assertIsNotNone(self.app.autosave_after)
        self.app._clear_current_autosave()
        self.assertIsNone(self.app.autosave_after)


class TestEstadoCorrupto(_BaseApp):
    """Un `estado.json` roto no rompe el arranque ni el cierre."""

    def test_arrancar_con_estado_corrupto(self):
        storage.estado_ui_path(self.config).write_text("{json roto", encoding="utf-8")
        app = TukulApp(self.config)
        try:
            app.update()
            self.assertEqual(app.recent_paths, [])
            app.load_document(self.documento)
            app._guardar_estado_ui()
        finally:
            app.destroy()
        # El cierre sano reescribe un estado válido encima del corrupto.
        self.assertIn("geometry", storage.load_ui_state(self.config))

    def test_estado_con_conversaciones_que_no_son_dict(self):
        storage.save_ui_state({"conversations": ["basura"]}, self.config)
        with patch.object(storage, "load_ui_state", return_value={"conversations": "texto"}):
            app = TukulApp(self.config)
            try:
                app.update()
                estado = app._snapshot_estado_ui()
            finally:
                app.destroy()
        self.assertEqual(estado["conversations"], {},
                         "Basura en disco se sustituye por un mapa vacío, no se propaga")

    def test_un_estado_que_no_se_puede_escribir_no_rompe_el_cierre(self):
        with patch.object(storage, "save_ui_state", side_effect=OSError("disco lleno")), \
                patch.object(modulo_app.logger, "warning") as aviso:
            self.app._guardar_estado_ui()
            self.app._guardar_preferencia_tema()
        self.assertEqual(aviso.call_count, 2, "Ambas escrituras avisan y siguen")
        self.assertTrue(self.app.winfo_exists())

    def test_la_conversacion_se_poda_a_los_documentos_vigentes(self):
        otro = str(self.raiz / "viejo.md")
        self.app.ui_state["conversations"] = {otro: []}
        estado = self.app._snapshot_estado_ui()
        self.assertNotIn(otro, estado["conversations"])


class TestRecientesYDocumentos(_BaseApp):
    """Un documento reciente desaparecido se retira de la lista con un aviso claro."""

    def test_un_reciente_inexistente_se_retira(self):
        fantasma = str(self.raiz / "borrado.md")
        self.app.recent_paths = [fantasma, str(self.documento)]
        with patch.object(modulo_app.messagebox, "showerror") as error:
            self.app._abrir_reciente(fantasma)
        error.assert_called_once()
        self.assertEqual(error.call_args[0][0], "Documento no disponible")
        self.assertNotIn(fantasma, self.app.recent_paths)

    def test_un_reciente_fuera_de_la_lista_solo_avisa(self):
        with patch.object(modulo_app.messagebox, "showerror") as error:
            self.app._abrir_reciente(str(self.raiz / "nunca-estuvo.md"))
        error.assert_called_once()
        self.assertEqual(self.app.recent_paths, [str(self.documento.resolve())])


class TestEnvioDesdeElInput(_BaseApp):
    """Validaciones que evitan turnos fantasma en el historial."""

    def test_enter_con_el_placeholder_activo_no_envia(self):
        self.app._placeholder_activo = True
        with patch.object(self.app, "request") as enviar:
            self.app._on_input_return(object())
        enviar.assert_not_called()

    def test_enter_con_texto_vacio_no_envia(self):
        self.app._placeholder_activo = False
        self.app.input.delete("1.0", "end")
        with patch.object(self.app, "request") as enviar:
            self.app._on_input_return(object())
        enviar.assert_not_called()

    def test_sin_key_avisa_sin_pintar_un_turno_del_usuario(self):
        self.app._placeholder_activo = False
        self.app.input.delete("1.0", "end")
        self.app.input.insert("1.0", "Hola")
        self.app._keys_llavero[self.app.active_profile] = ""
        with patch.object(self.app, "_resolver_credenciales", return_value=False), \
                patch.object(self.app, "request") as enviar:
            self.app._enviar_desde_input()
        enviar.assert_not_called()
        self.assertIn("Configura un perfil LLM", self.app.history.get("1.0", "end-1c"))

    def test_key_del_llavero_en_curso_avisa_de_espera(self):
        import threading

        self.app._placeholder_activo = False
        self.app.input.delete("1.0", "end")
        self.app.input.insert("1.0", "Hola")
        self.app._keys_llavero[self.app.active_profile] = ""
        self.app._llaves_en_curso[self.app.active_profile] = threading.Event()
        try:
            with patch.object(self.app, "_resolver_credenciales", return_value=False), \
                    patch.object(self.app, "request") as enviar:
                self.app._enviar_desde_input()
        finally:
            self.app._llaves_en_curso.pop(self.app.active_profile, None)
        enviar.assert_not_called()
        self.assertIn("Recuperando la API key", self.app.history.get("1.0", "end-1c"))


class _Grabador:
    """Doble mínimo sin `unittest.mock`.

    `MagicMock` crea mocks hijos de forma perezosa y, si el worker lo toca
    mientras el recolector corre en ese mismo hilo, CPython 3.13 aborta el
    proceso (se reprodujo con `--cov`). Este doble solo anota la llamada.
    """

    def __init__(self) -> None:
        self.llamadas: list[tuple] = []

    def __call__(self, *args, **kwargs) -> None:
        self.llamadas.append((args, kwargs))


class _SesionSinRed(_Grabador):
    """Sustituye a `LLMSessionManager` en el worker: anota y no sale a la red."""

    def stream_response(self, *args, **kwargs) -> None:
        self.llamadas.append((args, kwargs))

    def cancel(self, request_id: int) -> None:
        pass


class TestCicloDePeticion(_BaseApp):
    """`_ciclo_peticion` conecta el ciclo al llavero de ESTA ventana (1898-1904).

    RequestLifecycle resuelve la key dentro del worker. El cierre de la deuda
    del refactor es que esa resolución sea la de la ventana: `self.key` si ya
    está en sesión, y si no, la lectura diferida del llavero.
    """

    def _lanzar(self, request_id: int, **extra):
        sesion = _SesionSinRed()
        evento = __import__("threading").Event()
        ciclo = modulo_app.RequestLifecycle(
            chunks=self.app.chunks,
            publicar=self.app.control_queue.put_nowait,
            session=sesion,
            arrancar=modulo_app.WorkerThreads.start,
            esperar_key=lambda: self.app.key or self.app._esperar_key(),
        )
        ciclo.start(
            request_id=request_id, profile=self.app.profile, article="texto",
            packet="", conversation=[], cancel_event=evento, **extra,
        )
        modulo_app.WorkerThreads.esperar(5)
        return sesion

    def test_sin_key_en_sesion_el_worker_no_llega_al_proveedor(self):
        self.app._keys_llavero[self.app.active_profile] = ""
        with patch.dict(os.environ, {CLAVE: ""}):
            sesion = self._lanzar(42, request_type="normal", files=["a.md"])
        self.assertEqual(sesion.llamadas, [], "Sin key no se abre petición al proveedor")
        eventos = []
        while not self.app.control_queue.empty():
            eventos.append(self.app.control_queue.get_nowait())
        self.assertEqual(eventos, [("error", 42, "No pude responder: falta la API key", ["a.md"])])

    def test_con_key_en_sesion_llega_al_proveedor_con_esa_key(self):
        with patch.dict(os.environ, {CLAVE: ""}):
            self.app._add_session_key(self.app.active_profile, "key-de-sesion")
            with patch.object(self.app, "_esperar_key",
                              side_effect=AssertionError("no debe leer el llavero")):
                sesion = self._lanzar(43, request_type="normal")
        self.assertEqual(len(sesion.llamadas), 1)
        args, kwargs = sesion.llamadas[0]
        self.assertEqual(args[1], "key-de-sesion")
        self.assertEqual(args[3], "", "Sin contexto adicional, el paquete va vacío")
        self.assertEqual(kwargs["request_id"], 43)


class TestValidacionDeTamano(_BaseApp):
    """El límite se comprueba ANTES de lanzar el worker: nada sale si no cabe."""

    def _enviar_con_tope(self, max_total: int):
        self.app.profile.max_total_model_tokens = max_total
        self.app.profile.max_output_tokens = max(1, min(1000, max_total))
        with patch.object(self.app.llm, "stream_response") as enviar, \
                patch.object(modulo_app.messagebox, "showerror") as error:
            self.app.request("Una consulta")
            self._asentar()
        return enviar, error

    def test_peticion_normal_demasiado_grande_no_llega_al_modelo(self):
        enviar, error = self._enviar_con_tope(10)
        enviar.assert_not_called()
        error.assert_called_once()
        self.assertIn("demasiado grande", error.call_args[0][0])
        self.assertFalse(self.app.session.request_active)

    def test_revision_demasiado_grande_no_llega_al_modelo(self):
        self.app.profile.max_total_model_tokens = 10
        self.app.profile.max_output_tokens = 5
        with patch.object(self.app.llm, "stream_response") as enviar, \
                patch.object(modulo_app.messagebox, "showerror") as error:
            self.app.review()
            self._asentar()
        enviar.assert_not_called()
        self.assertIn("demasiado largo", error.call_args[0][0])
        self.assertIs(self.app.estado_actual, EstadoUI.ERROR)

    def test_un_fallo_que_no_es_de_tamano_es_error_de_preparacion(self):
        with patch.object(self.app.llm, "stream_response") as enviar, \
                patch.object(modulo_app, "estimate_prompt_tokens",
                             side_effect=MemoryError("sin memoria")), \
                patch.object(modulo_app.messagebox, "showerror") as error:
            self.app.review()
            self._asentar()
        enviar.assert_not_called()
        self.assertIn("Error interno", error.call_args[0][0])


class TestIngestionDeVersionAnterior(_BaseApp):
    """Una respuesta de una petición ya cerrada no se pinta (línea 2022)."""

    def test_un_complete_de_una_peticion_olvidada_se_descarta(self):
        self.app.request_types.clear()
        self.app.chunks.append(999, "texto viejo")
        self.app.control_queue.put_nowait(("complete", 999, "texto viejo", [], (None, None), "normal"))
        self.app.process_ui_events()
        self.assertNotIn("texto viejo", self.app.history.get("1.0", "end-1c"))
        self.assertEqual(self.app.chunks.pending_requests(), 0,
                         "El texto de una petición olvidada se descarta, no se pinta")


class TestDiagnosticoDeErrores(_BaseApp):
    """`handle_callback_error` traduce el fallo; lo trivial no abre un modal."""

    def _reportar(self, exc: BaseException):
        with patch.object(modulo_app.messagebox, "showerror") as error:
            self.app.handle_callback_error(type(exc), exc, None)
        return error

    def test_un_error_de_tk_avisa(self):
        error = self._reportar(tk.TclError("bad window path name"))
        self.assertIn("contratiempo", self.app.status.get())
        error.assert_called_once()

    def test_un_error_de_clasificador_de_tk_no_abre_modal(self):
        """Los fallos de la ventana que el propio manejador resuelve no abren un modal."""
        error = self._reportar(tk.TclError("tcl_stub"))
        error.assert_not_called()
        self.assertIn("contratiempo", self.app.status.get())

    def test_sin_memoria(self):
        error = self._reportar(MemoryError("out of memory"))
        self.assertIn("sin memoria", self.app.status.get())
        error.assert_called_once()

    def test_sin_permisos(self):
        error = self._reportar(PermissionError("permission denied: /x.md"))
        self.assertIn("permisos", self.app.status.get())
        error.assert_called_once()

    def test_un_error_desconocido_abre_el_modal(self):
        error = self._reportar(ValueError("algo raro"))
        self.assertIn("no salió como esperaba", self.app.status.get())
        self.assertIn("tukul.log", error.call_args[0][1])


class TestLlaveroNoDisponible(_BaseApp):
    """Un llavero ausente o caído no cuenta como «falta la key»."""

    def _precargar(self, *parches):
        """Lanza la lectura del llavero y espera a que el hilo termine (con tope)."""
        self.app._keys_llavero.clear()
        with parches[0], parches[1]:
            self.app._precargar_key(self.app.active_profile)
            self.app._esperar_key(timeout=2.0)

    def test_backend_ausente_cachea_vacio_sin_llamar_al_llavero(self):
        with patch.object(storage, "credential_backend_disponible", return_value=False), \
                patch.object(storage, "load_key") as leer, \
                patch.object(self.app, "_llaves_en_curso", {}):
            self.app._precargar_key(self.app.active_profile)
        leer.assert_not_called()
        self.assertEqual(self.app._keys_llavero[self.app.active_profile], "")

    def test_un_backend_que_no_responde_publica_el_aviso(self):
        self._precargar(
            patch.object(storage, "credential_backend_disponible", return_value=True),
            patch.object(storage, "load_key",
                         side_effect=storage.KeyringUnavailableError("d-bus caído")),
        )
        eventos = []
        while not self.app.control_queue.empty():
            eventos.append(self.app.control_queue.get_nowait())
        self.assertIn(("keyring_unavailable", self.app.active_profile), eventos)
        self.assertEqual(self.app._keys_llavero[self.app.active_profile], "",
                         "Se cachea vacío para no reintentar en bucle")

    def test_un_error_ajeno_del_backend_no_rompe_la_ui(self):
        self._precargar(
            patch.object(storage, "credential_backend_disponible", return_value=True),
            patch.object(storage, "load_key", side_effect=RuntimeError("backend raro")),
        )
        self.assertEqual(self.app._keys_llavero[self.app.active_profile], "")
        self.assertNotIn(self.app.active_profile, self.app._llaves_en_curso,
                         "La lectura terminada no debe quedar como pendiente")


class TestPortapapelesDelHistorial(_BaseApp):
    """Copiar el mensaje bajo el cursor (líneas 1384-1399)."""

    def setUp(self):
        super().setUp()
        # Un mensaje y una nota, cada uno en su rango de etiqueta.
        self.app.append("Tú", "texto del usuario")
        self.app.append("Tukul", "respuesta del asistente")
        self._asentar()

    def _indice_de(self, texto: str) -> str:
        indice = self.app.history.search(texto, "1.0")
        self.assertTrue(indice, f"{texto!r} debe estar en el historial")
        return indice

    def _copiar_en(self, indice: str) -> None:
        self.app.history.update()
        x, y, ancho, alto = self.app.history.bbox(indice)
        evento = type("E", (), {"x": x + ancho // 2, "y": y + alto // 2})()
        with patch.object(modulo_app, "_en_el_hilo_de_tk", return_value=True):
            self.app._copiar_mensaje(evento)

    def test_copia_el_mensaje_bajo_el_cursor(self):
        self._copiar_en(self._indice_de("respuesta del asistente"))
        self.assertIn("respuesta del asistente", self.app.clipboard_get())
        self.assertIn("copiado", self.app.status.get())

    def test_sobre_un_hueco_avisa(self):
        """Debajo del último mensaje no hay etiqueta: se informa, no se copia."""
        ultima = int(self.app.history.index("end-1c").split(".")[0])
        self._copiar_en(f"{ultima}.0")
        self.assertIn("No hay mensaje", self.app.status.get())


class TestTamanoInicial(unittest.TestCase):
    """`_aplicar_tamano_inicial` sin pantalla utilizable (líneas 399-400).

    En un escritorio real la rama normal siempre gana; la de repliegue es la
    que se ejecuta en pantallas no reportadas (Xvfb mal configurado, CI sin
    gestor de escritorio) y fija un mínimo que no deje la ventana inusable.
    """

    def _aplicar_con(self, ancho: int, alto: int) -> tuple[list, list]:
        app = TukulApp.__new__(TukulApp)
        minimos: list = []
        geometrias: list = []
        app.minsize = lambda *a: minimos.append(a)
        app.geometry = lambda g: geometrias.append(g)
        with patch.object(TukulApp, "winfo_screenwidth", return_value=ancho), \
                patch.object(TukulApp, "winfo_screenheight", return_value=alto):
            app._aplicar_tamano_inicial()
        return minimos, geometrias

    def test_sin_pantalla_reportada_usa_el_tamano_por_defecto(self):
        minimos, geometrias = self._aplicar_con(0, 0)
        self.assertEqual(minimos, [(720, 540)])
        self.assertEqual(geometrias, ["1180x760"])

    def test_con_pantalla_normal_ocupa_el_ochenta_por_ciento(self):
        minimos, geometrias = self._aplicar_con(1920, 1080)
        self.assertEqual(minimos, [(720, 540)])
        self.assertEqual(geometrias, ["1400x864"])


class TestMenuDeRecientes(_BaseApp):
    """El submenú reconstruye sus entradas con captura temprana de la ruta (línea 1184)."""

    def test_vacio_deshabilita_la_entrada_y_no_ofrece_limpiar(self):
        self.app.recent_paths = []
        self.app._refrescar_menu_recientes()
        self.assertEqual(self.app.menu_recientes.index("end"), 0)
        self.assertEqual(self.app.menu_recientes.type(0), "command")
        self.assertEqual(self.app.menu_recientes.entrycget(0, "state"), "disabled")

    def test_cada_entrada_abre_su_propia_ruta(self):
        """El clásico late binding haría que todas abrieran la última."""
        a = self.raiz / "a.md"
        b = self.raiz / "b.md"
        a.write_text("Contenido de A", encoding="utf-8")
        b.write_text("Contenido de B", encoding="utf-8")
        self.app.recent_paths = [str(a), str(b)]
        self.app._refrescar_menu_recientes()
        abiertas: list[str] = []
        with patch.object(self.app, "_abrir_reciente", side_effect=abiertas.append):
            for indice in (0, 1):
                self.app.menu_recientes.invoke(indice)
        self.assertEqual(abiertas, [str(a), str(b)])
        self.assertEqual(self.app.menu_recientes.type(2), "separator")
        self.assertEqual(self.app.menu_recientes.index("end"), 3)
        self.app.menu_recientes.delete(0, "end")
        with patch.object(self.app, "_limpiar_recientes") as limpiar:
            self.app._refrescar_menu_recientes()
            self.app.menu_recientes.invoke(3)
        limpiar.assert_called_once()


class TestDialogoDeContexto(_BaseApp):
    """«Contexto de artículos»: añadir, quitar y avisar al vaciar la lista."""

    def _dialogo(self) -> tk.Toplevel:
        antes = set(self.app.winfo_children())
        self.app.manage_references()
        self._asentar()
        nuevos = [hijo for hijo in self.app.winfo_children() if hijo not in antes]
        self.assertEqual(len(nuevos), 1)
        return nuevos[0]

    def _descendientes(self, widget, tipo):
        encontrados = []
        for hijo in widget.winfo_children():
            if isinstance(hijo, tipo):
                encontrados.append(hijo)
            encontrados.extend(self._descendientes(hijo, tipo))
        return encontrados

    def test_anadir_un_articulo_lo_lista_y_lo_autoriza(self):
        extra = self.raiz / "extra.md"
        extra.write_text("Texto de contexto adicional", encoding="utf-8")
        dialogo = self._dialogo()
        lista = self._descendientes(dialogo, tk.Listbox)[0]
        boton_anadir = next(b for b in self._descendientes(dialogo, ttk.Button)
                            if b.cget("text") == "Añadir artículos…")
        with patch.object(modulo_app.filedialog, "askopenfilenames",
                          return_value=(str(extra),)) , \
                patch.object(self.app, "_ask_to_authorize_articles", return_value=True):
            boton_anadir.invoke()
            self._asentar()
        self.assertEqual(lista.size(), 1)
        self.assertEqual(lista.get(0), "extra.md")
        self.assertIn("añadido", self.app.status.get())
        dialogo.destroy()

    def test_rechazar_la_autorizacion_no_anade_nada(self):
        extra = self.raiz / "extra.md"
        extra.write_text("Texto de contexto adicional", encoding="utf-8")
        dialogo = self._dialogo()
        lista = self._descendientes(dialogo, tk.Listbox)[0]
        boton_anadir = next(b for b in self._descendientes(dialogo, ttk.Button)
                            if b.cget("text") == "Añadir artículos…")
        with patch.object(modulo_app.filedialog, "askopenfilenames",
                          return_value=(str(extra),)), \
                patch.object(self.app, "_ask_to_authorize_articles", return_value=False):
            boton_anadir.invoke()
            self._asentar()
        self.assertEqual(lista.size(), 0)
        dialogo.destroy()

    def test_quitar_el_seleccionado_sin_seleccion_no_cambia_nada(self):
        extra = self.raiz / "extra.md"
        extra.write_text("Texto de contexto adicional", encoding="utf-8")
        self.app._add_references([str(extra)])
        dialogo = self._dialogo()
        lista = self._descendientes(dialogo, tk.Listbox)[0]
        boton_quitar = next(b for b in self._descendientes(dialogo, ttk.Button)
                            if b.cget("text") == "Quitar seleccionadas")
        boton_quitar.invoke()
        self.assertEqual(lista.size(), 1, "Sin selección no se quita nada")
        lista.selection_set(0)
        boton_quitar.invoke()
        self.assertEqual(lista.size(), 0)
        self.assertEqual(self.app.status.get(), "Contexto de artículos actualizado.")
        dialogo.destroy()


class TestPipelineDeIdeas(_BaseApp):
    """El pipeline de CVEs termina en el diálogo seleccionable o en un aviso claro."""

    def setUp(self):
        super().setUp()
        self.pendientes: list = []
        # `after(0, ...)` se sustituye por una cola: el callback se ejecuta
        # desde el cuerpo del test, nunca desde sí mismo (un diálogo anidado
        # programa otro `after` y un shim inmediato recursaría sin fin).
        self._parche_after = patch.object(
            self.app, "after",
            side_effect=lambda ms, f=None, *a: self.pendientes.append((f, a)) or "id",
        )
        self._parche_after.start()
        self.addCleanup(self._parche_after.stop)
        self.modal: tk.Toplevel | None = None

    def _drenar(self) -> None:
        while self.pendientes:
            funcion, args = self.pendientes.pop(0)
            if funcion is not None:
                funcion(*args)
        self._asentar()

    def _dialogo_padre(self) -> tk.Toplevel:
        padre = tk.Toplevel(self.app)
        self._asentar()
        return padre

    def _pipeline(self, padre: tk.Toplevel):
        with patch.object(modulo_app, "FeedOrchestrator", _OrquestadorConDatos), \
                patch.object(modulo_app, "FEED_CACHE_DIR", self.raiz), \
                patch.object(self.app, "_llm_de_ideas", return_value=None):
            publicado = self.app._ejecutar_pipeline_ideas(
                padre, self.app.profile, "clave", self.raiz / "cache.json", lambda: None)
        self._drenar()
        return publicado

    def _abrir_dialogo_de_ideas(self, padre: tk.Toplevel) -> tk.Toplevel:
        """Ejecuta el pipeline y devuelve el diálogo de ideas que abre.

        `tk.Toplevel.__init__` crea el widget bajo la raíz por defecto de Tk,
        que en ese momento es el padre pasado; el diálogo queda, por tanto,
        como hijo suyo. Tk solo lo lista tras procesar eventos, así que se
        bombean idle/update antes de buscarlo.
        """
        self._pipeline(padre)
        self._asentar(10)
        hijos = [h for h in padre.winfo_children() if isinstance(h, tk.Toplevel)]
        self.assertEqual(len(hijos), 1, f"Debe abrirse el diálogo de ideas: {hijos}")
        return hijos[0]

    def test_sin_correlaciones_avisa_y_no_abre_dialogo(self):
        padre = self._dialogo_padre()
        with patch.object(modulo_app, "CorrelationEngine") as motor, \
                patch.object(self.app, "_publicar_error_ideas") as publicar:
            motor.return_value.correlate.return_value = []
            publicado = self._pipeline(padre)
        self.assertFalse(publicado)
        publicar.assert_called_once()
        self.assertIn("correlaciones", publicar.call_args[0][1])
        padre.destroy()

    def test_una_correlacion_abre_el_dialogo_de_seleccion(self):
        padre = self._dialogo_padre()
        with patch.object(self.app, "_show_idea_selection_dialog") as dialogo:
            publicado = self._pipeline(padre)
        self.assertTrue(publicado)
        dialogo.assert_called_once()
        _, ideas, entries, correlations, _ = dialogo.call_args[0]
        self.assertTrue(ideas)
        self.assertTrue(correlations)
        self.assertTrue(entries)
        padre.destroy()

    def _pipeline_capturando_dialogo(self, padre) -> None:
        """Abre el pipeline y apunta el diálogo: `winfo_children()` no lo lista
        hasta que Tk lo registra, así que se captura su `destroy()`."""
        self._pipeline(padre)

    def test_desarrollar_la_idea_la_deja_como_contexto_autorizado(self):
        padre = self._dialogo_padre()
        modal = self._abrir_dialogo_de_ideas(padre)
        lista = self._todos(modal, tk.Listbox)[0]
        lista.selection_set(0)
        lista.event_generate("<<ListboxSelect>>")
        self._asentar()
        boton = next(b for b in self._todos(modal, ttk.Button)
                     if b.cget("text") == "Desarrollar esta idea")
        boton.invoke()
        self._asentar()

        ideas = [a for a in self.app.context_articles if a.label.startswith("Idea:")]
        self.assertEqual(len(ideas), 1, "La idea elegida es una instantánea de contexto")
        self.assertIn("Idea seleccionada", self.app.status.get())
        self.assertFalse(modal.winfo_exists(), "El diálogo se cierra al desarrollar")
        padre.destroy()

    def test_desarrollar_sin_seleccion_avisa_y_no_cierra(self):
        padre = self._dialogo_padre()
        modal = self._abrir_dialogo_de_ideas(padre)
        boton = next(b for b in self._todos(modal, ttk.Button)
                     if b.cget("text") == "Desarrollar esta idea")
        with patch.object(modulo_app.messagebox, "showinfo") as aviso:
            boton.invoke()
        aviso.assert_called_once()
        self.assertTrue(modal.winfo_exists())
        self.assertEqual([a for a in self.app.context_articles
                          if a.label.startswith("Idea:")], [])
        padre.destroy()

    def _todos(self, widget, tipo):
        resultado = []
        for hijo in widget.winfo_children():
            if isinstance(hijo, tipo):
                resultado.append(hijo)
            resultado.extend(self._todos(hijo, tipo))
        return resultado


class _OrquestadorConDatos:
    """Doble del orquestador: dos entradas que comparten CVE → una correlación."""

    def __init__(self, **_kwargs):
        pass

    def fetch_all(self, **_kwargs):
        from datetime import UTC, datetime

        from tukul_core.models import FeedEntry

        ahora = datetime.now(UTC)
        return [
            FeedEntry(source_id="nvd:CVE-2026-4242", source="nvd",
                      title="CVE-2026-4242", description="Fallo crítico",
                      url="https://nvd.nist.gov/vuln/detail/CVE-2026-4242",
                      published=ahora, severity=9.1),
            FeedEntry(source_id="kev:CVE-2026-4242", source="kev",
                      title="CVE-2026-4242", description="Explotado",
                      url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                      published=ahora, severity=9.1),
        ]


class TestAccionesDeContexto(_BaseApp):
    """Autorizar sin artículos no pregunta; un fallo de la fuente no muere en silencio."""

    def test_autorizar_sin_etiquetas_no_pregunta(self):
        with patch.object(modulo_app.messagebox, "askyesno") as preguntar:
            self.assertFalse(self.app._ask_to_authorize_articles([], self.app))
        preguntar.assert_not_called()

    def test_un_fallo_inesperado_de_la_fuente_de_amenazas_se_reporta(self):
        """Línea 2270: el hilo daemon no muere callado ante un error ajeno."""
        recibidos: list = []
        with patch.object(modulo_app, "build_threat_context", side_effect=ValueError("json roto")), \
                patch.object(self.app, "_on_threat_feed_error",
                             side_effect=lambda *a: recibidos.append(a)), \
                patch.object(modulo_app.messagebox, "askyesno", return_value=True), \
                patch.object(self.app, "after",
                             side_effect=lambda ms, f=None, *a: (f(*a) if f else None) or "id"):
            self.app._fetch_threat_feed(self.app, lambda: None)
            self._asentar(50)
            modulo_app.WorkerThreads.esperar(5)
        self._asentar()
        self.assertTrue(recibidos, "El fallo debe llegar al hilo de Tk")
        self.assertIn("json roto", recibidos[0][1])


class TestDeshacerDeRevision(_BaseApp):
    """Deshacer nunca vuelca el texto de un documento sobre otro (líneas 2176-2177)."""

    def test_sin_instantanea_no_hace_nada(self):
        self.app.scope.review_before = ""
        texto = self.app.editor.get("1.0", "end-1c")
        self.app.undo_review()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), texto)

    def test_un_ajuste_de_otro_documento_se_rechaza_sin_tocar_el_editor(self):
        from tukul_ui.document_scope import DocumentScope

        texto_antes = self.app.editor.get("1.0", "end-1c")
        self.app.scope = DocumentScope(document_path=self.raiz / "otro.md")
        self.app.scope.review_before = "texto del otro artículo"
        self.app.undo_review()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), texto_antes)
        self.assertEqual(self.app.scope.review_before, "", "La instantánea ajena se olvida")
        self.assertIn("otro documento", self.app.status.get())

    def test_un_ajuste_del_mismo_documento_se_deshace(self):
        texto_antes = self.app.editor.get("1.0", "end-1c")
        self.app.snapshot_for_undo("Texto anterior a la corrección.")
        self.app.undo_review()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "Texto anterior a la corrección.")
        self.assertNotEqual(texto_antes, "Texto anterior a la corrección.")


class TestPlaceholderReal(_BaseApp):
    """El placeholder se retira al enfocar y vuelve al salir si el campo quedó vacío."""

    def test_foco_retira_y_devuelve_el_placeholder(self):
        self.app.input.focus_force()
        self._asentar()
        self.assertFalse(self.app._placeholder_activo)
        self.assertEqual(self.app.input.get("1.0", "end-1c"), "")

        self.app.editor.focus_force()
        self._asentar()
        self.assertTrue(self.app._placeholder_activo)
        self.assertEqual(self.app.input.get("1.0", "end-1c"),
                         self.app._placeholder_texto)


class TestSeleccionarTodo(_BaseApp):
    def test_control_a_selecciona_el_widget_que_recibe_el_evento(self):
        self.app.editor.focus_force()
        self._asentar()
        self.app.editor.event_generate("<Control-a>")
        self._asentar()
        seleccion = self.app.editor.get("sel.first", "sel.last")
        self.assertEqual(seleccion, self.app.editor.get("1.0", "end-1c"))


class TestEditUndoRedo(_BaseApp):
    """Los ayudantes toleran un widget que ya no puede deshacer (TclError)."""

    def test_undo_sin_nada_que_deshacer_no_rompe(self):
        self.app.editor.edit_reset()
        with patch.object(self.app.editor, "edit_undo", side_effect=tk.TclError("nada")):
            TukulApp._edit_undo(self.app.editor)
        with patch.object(self.app.editor, "edit_redo", side_effect=tk.TclError("nada")):
            TukulApp._edit_redo(self.app.editor)

    def test_undo_si_hay_historial(self):
        self.app.editor.insert("end", " editado")
        self.app.editor.edit_modified(False)
        TukulApp._edit_undo(self.app.editor)
        self.assertNotIn(" editado", self.app.editor.get("1.0", "end-1c"))


class TestRestaurarGeometria(_BaseApp):
    """Una geometría guardada que no cabe se corrige; con pantalla sin medir se ignora."""

    def test_pantalla_sin_medir_no_aplica_nada(self):
        """Línea 485: sin dimensiones creíbles, lo guardado no se toca."""
        self.app.ui_state["geometry"] = "900x600+10+10"
        antes = self.app.geometry()
        with patch.object(TukulApp, "winfo_screenwidth", return_value=0), \
                patch.object(TukulApp, "winfo_screenheight", return_value=0), \
                patch.object(self.app, "geometry") as aplicar:
            self.app._restaurar_geometria()
        aplicar.assert_not_called()

    def test_valor_no_texto_se_ignora(self):
        self.app.ui_state["geometry"] = 1180
        with patch.object(self.app, "geometry") as aplicar:
            self.app._restaurar_geometria()
        aplicar.assert_not_called()

    def test_una_geometria_en_blanco_se_ignora(self):
        self.app.ui_state["geometry"] = "   "
        with patch.object(self.app, "geometry") as aplicar:
            self.app._restaurar_geometria()
        aplicar.assert_not_called()

    def test_una_geometria_valida_se_aplica(self):
        self.app.ui_state["geometry"] = "900x600+10+10"
        with patch.object(self.app, "geometry") as aplicar:
            self.app._restaurar_geometria()
        aplicar.assert_called_once()

    def test_miniatura_guardada_se_agranda_al_sanear(self):
        """Línea 485 del saneador: 1x1 se eleva al mínimo legible."""
        self.assertEqual(TukulApp._geometria_saneada("1x1+0+0", 1920, 1080), "720x540+0+0")


class TestHiloDeTk(unittest.TestCase):
    """La guarda que evita programar `after()` desde un worker (línea 157)."""

    def test_desde_el_hilo_principal_es_valido(self):
        self.assertTrue(modulo_app._en_el_hilo_de_tk(None))

    def test_desde_un_worker_no(self):
        import threading

        resultados: list[bool] = []
        hilo = threading.Thread(target=lambda: resultados.append(
            modulo_app._en_el_hilo_de_tk(None)))
        hilo.start()
        hilo.join(5)
        self.assertEqual(resultados, [False])


if __name__ == "__main__":
    unittest.main()
