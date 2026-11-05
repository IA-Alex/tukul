"""Contrato de `RequestLifecycle`: un worker, un evento final, cero Tk.

Antes del módulo, el mismo bloque vivía cuatro veces en `TukulApp`; estas
pruebas fijan lo que esas copias debían garantizar y alguna no cumplía.
"""

from __future__ import annotations

import threading
import unittest

from tukul_core.models import ChatMessage, LlmProfile
from tukul_ui.request_lifecycle import RequestLifecycle


class _Chunks:
    """Doble del ChunkBuffer: memoriza y olvida por petición."""

    def __init__(self) -> None:
        self.por_peticion: dict[int, list[str]] = {}

    def append(self, request_id: int, texto: str) -> None:
        self.por_peticion.setdefault(request_id, []).append(texto)

    def discard(self, request_id: int) -> None:
        self.por_peticion.pop(request_id, None)


class _Sesion:
    """Doble de LLMSessionManager: emite chunks y termina como se le pida."""

    def __init__(self, *, fallar: bool = False, texto: str = "respuesta") -> None:
        self.fallar = fallar
        self.texto = texto
        self.llamadas: list[dict] = []
        self.canceladas: list[int] = []

    def stream_response(self, profile, api_key, article, packet, conversation,
                        on_chunk, on_error, on_complete, request_id=None,
                        cancel_event=None):
        self.llamadas.append({
            "api_key": api_key, "article": article, "packet": packet,
            "conversation": list(conversation), "request_id": request_id,
            "cancel_event": cancel_event,
        })
        on_chunk(self.texto)
        if self.fallar:
            on_error("boom")
        else:
            on_complete(self.texto, (3, 2))

    def cancel(self, request_id: int) -> None:
        self.canceladas.append(request_id)


def _perfil() -> LlmProfile:
    return LlmProfile(provider="openai_compatible", endpoint="https://x.test", model="m")


class _Base(unittest.TestCase):
    def construir(self, sesion, *, esperar_key=lambda: "k", ejecutar_ya=False):
        """Prepara el ciclo con un `arrancar` que solo registra el worker.

        Por defecto NO arranca el hilo: así no hay carrera entre el worker y el
        propio test (publicar antes de leer `publicados` o al revés). `correr()`
        ejecuta el trabajo de forma determinista.
        """
        self.publicados: list[tuple] = []
        self.trabajos: list = []
        chunks = _Chunks()

        def arrancar(work):
            self.trabajos.append(work)
            if ejecutar_ya:
                hilo = threading.Thread(target=work, daemon=True)
                hilo.start()
                hilo.join(5)

        ciclo = RequestLifecycle(
            chunks=chunks,
            publicar=self.publicados.append,
            session=sesion,
            arrancar=arrancar,
            esperar_key=esperar_key,
        )
        return ciclo, chunks

    def correr(self):
        while self.trabajos:
            self.trabajos.pop(0)()


class TestEnvioCorrecto(_Base):
    def test_publica_complete_con_texto_files_y_usage(self):
        sesion = _Sesion(texto="Hola")
        ciclo, chunks = self.construir(sesion)
        evento = threading.Event()
        ciclo.start(
            request_id=7, profile=_perfil(), article="art", packet="ctx",
            conversation=[ChatMessage("user", "hola")], cancel_event=evento,
            files=["nvd:recent-24h"],
        )
        self.correr()
        tipo, request_id, texto, files, usage, request_type = self.publicados[0]
        self.assertEqual((tipo, request_id, texto, files), ("complete", 7, "Hola", ["nvd:recent-24h"]))
        self.assertEqual(usage, (3, 2))
        self.assertEqual(request_type, "normal")
        self.assertEqual(chunks.por_peticion[7], ["Hola"])

    def test_el_texto_va_a_chunks_y_no_a_la_cola_de_control(self):
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion)
        ciclo.start(request_id=1, profile=_perfil(), article="a", packet="",
                    conversation=[], cancel_event=threading.Event())
        self.correr()
        self.assertTrue(all(evento[0] in {"complete", "error"} for evento in self.publicados))

    def test_la_revision_se_publica_con_su_tipo(self):
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion)
        ciclo.start(request_id=2, profile=_perfil(), article="a", packet="",
                    conversation=[], cancel_event=threading.Event(),
                    request_type="review")
        self.correr()
        self.assertEqual(self.publicados[0][-1], "review")

    def test_el_evento_de_cancelacion_viaja_con_la_peticion(self):
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion)
        evento = threading.Event()
        ciclo.start(request_id=3, profile=_perfil(), article="a", packet="",
                    conversation=[], cancel_event=evento)
        self.correr()
        self.assertIs(sesion.llamadas[0]["cancel_event"], evento)
        self.assertEqual(sesion.llamadas[0]["request_id"], 3)

    def test_la_conversacion_se_congela_antes_del_worker(self):
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion)
        conversacion = [ChatMessage("user", "primera")]
        ciclo.start(request_id=4, profile=_perfil(), article="a", packet="",
                    conversation=conversacion, cancel_event=threading.Event())
        conversacion.append(ChatMessage("user", "añadida después"))
        self.correr()
        self.assertEqual([m.content for m in sesion.llamadas[0]["conversation"]], ["primera"])


class TestFallos(_Base):
    def test_un_error_se_publica_como_evento_error_con_files(self):
        sesion = _Sesion(fallar=True)
        ciclo, _ = self.construir(sesion)
        ciclo.start(request_id=5, profile=_perfil(), article="a", packet="",
                    conversation=[], cancel_event=threading.Event(), files=["x.md"])
        self.correr()
        self.assertEqual(self.publicados[0], ("error", 5, "No pude responder: boom", ["x.md"]))

    def test_sin_key_publica_error_y_no_llama_al_proveedor(self):
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion, esperar_key=lambda: "")
        ciclo.start(request_id=6, profile=_perfil(), article="a", packet="",
                    conversation=[], cancel_event=threading.Event())
        self.correr()
        self.assertEqual(sesion.llamadas, [])
        self.assertEqual(self.publicados[0][0], "error")
        self.assertIn("falta la API key", self.publicados[0][2])

    def test_la_key_se_resuelve_dentro_del_worker(self):
        """Leerla en el constructor bloquearía el hilo de Tk."""
        pedidas: list[str] = []
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion, esperar_key=lambda: pedidas.append("x") or "k")
        self.assertEqual(pedidas, [])
        ciclo.start(request_id=8, profile=_perfil(), article="a", packet="",
                    conversation=[], cancel_event=threading.Event())
        self.correr()
        self.assertEqual(pedidas, ["x"])


class TestCancelacion(_Base):
    def test_cancelar_descarta_los_pendientes_y_cierra_el_stream(self):
        sesion = _Sesion()
        ciclo, chunks = self.construir(sesion)
        chunks.append(9, "texto tardío")
        ciclo.cancel(9)
        self.assertEqual(chunks.por_peticion, {})
        self.assertEqual(sesion.canceladas, [9])

    def test_cancelar_no_toca_el_evento_de_cancelacion(self):
        """La UI es dueña de sus eventos: dos peticiones no deben cruzarse."""
        sesion = _Sesion()
        ciclo, _ = self.construir(sesion)
        evento = threading.Event()
        ciclo.cancel(10)
        self.assertFalse(evento.is_set())
        self.assertEqual(sesion.canceladas, [10])


if __name__ == "__main__":
    unittest.main()
