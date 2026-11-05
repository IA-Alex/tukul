"""Ciclo de vida de una petición: de la UI al proveedor y de vuelta.

TukulApp tenía el mismo bloque repetido cuatro veces (revisión, envío normal,
contexto de amenazas e ideas): crear el hilo, resolver la key dentro del worker
y publicar `complete`/`error` en la cola de control. Cada copia era una
oportunidad de divergir, y de hecho divergieron: la cancelación cruzada entre
peticiones nació de una de esas copias.

Aquí vive **solo** el patrón de las peticiones al LLM. Lo que pertenece a la
interfaz (aprobación de contexto, pintura de texto, diálogos y `estado.json`)
sigue en `TukulApp`: este módulo no conoce Tk.

Canales, tal como los describe `docs/QUEUE_POLICY.md`:

- texto incremental → `chunks` (`ChunkBuffer`), nunca la cola de control;
- `complete`/`error` → `control_queue`, exactamente uno por petición.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from tukul_core.models import ChatMessage, LlmProfile


class SessionLike(Protocol):
    """Lo que el módulo necesita de `LLMSessionManager` (permite dobles)."""

    def stream_response(
        self,
        profile: LlmProfile,
        api_key: str,
        article: str,
        packet: str,
        conversation: Iterable[ChatMessage],
        *,
        on_chunk: Callable[[str], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[str, tuple[int | None, int | None]], None],
        request_id: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None: ...

    def cancel(self, request_id: int) -> None: ...


class ChunksLike(Protocol):
    def append(self, request_id: int, texto: str) -> None: ...

    def discard(self, request_id: int) -> None: ...


class RequestLifecycle:
    """Arranca, cancela y publica peticiones al LLM.

    `publicar` es la única salida del módulo: una tupla con el mismo formato
    que consumía `TukulApp._dispatch_ui_event`.
    """

    def __init__(
        self,
        *,
        chunks: ChunksLike,
        publicar: Callable[[tuple[Any, ...]], None],
        session: SessionLike,
        arrancar: Callable[[Callable[[], Any]], Any],
        esperar_key: Callable[[], str],
    ) -> None:
        self._chunks = chunks
        self._publicar = publicar
        self._session = session
        self._arrancar = arrancar
        self._esperar_key = esperar_key

    def start(
        self,
        *,
        request_id: int,
        profile: LlmProfile,
        article: str,
        packet: str,
        conversation: Iterable[ChatMessage],
        cancel_event: threading.Event,
        request_type: str = "normal",
        files: list[str] | None = None,
        api_key: str = "",
    ) -> None:
        """Lanza la petición en un worker y publica el evento final.

        La key se resuelve **dentro** del worker: leerla en el hilo de Tk
        congelaba la interfaz mientras D-Bus respondía.
        """
        archivos = list(files or [])
        # El generador se materializa aquí: el worker corre en otro hilo y la
        # conversación puede cambiar mientras tanto.
        mensajes = list(conversation)

        def work() -> None:
            clave = api_key or self._esperar_key()
            if not clave:
                self._publicar(
                    ("error", request_id, "No pude responder: falta la API key", archivos)
                )
                return
            self._session.stream_response(
                profile,
                clave,
                article,
                packet,
                mensajes,
                on_chunk=lambda chunk: self._chunks.append(request_id, chunk),
                on_error=lambda error: self._publicar(
                    ("error", request_id, f"No pude responder: {error}", archivos)
                ),
                on_complete=lambda result, usage: self._publicar(
                    ("complete", request_id, result, archivos, usage, request_type)
                ),
                request_id=request_id,
                cancel_event=cancel_event,
            )

        self._arrancar(work)

    def cancel(self, request_id: int) -> None:
        """Descarta lo pendiente de la petición y cierra su stream HTTP.

        No marca el `cancel_event`: lo hace la UI, que es su dueña, para que
        cancelar una petición no toque el evento de otra.
        """
        self._chunks.discard(request_id)
        self._session.cancel(request_id)

