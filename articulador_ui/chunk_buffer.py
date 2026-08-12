"""Canal de texto en streaming entre los hilos de trabajo y la interfaz."""
from __future__ import annotations

import threading


class ChunkBuffer:
    """Acumulador de fragmentos de respuesta, separado de la cola de control.

    Los chunks NO viajan por la cola de eventos de control. Cuando compartían
    cola, una ráfaga de fragmentos podía llenarla y dejar la finalización de la
    petición esperando detrás: `complete` y `error` usaban inserciones
    bloqueantes, así que el hilo de trabajo se detenía con la conexión abierta
    hasta que la interfaz drenara.

    Aquí el productor solo toma un lock y añade a una lista: nunca bloquea y
    nunca descarta. El consumidor recoge de una vez todo lo acumulado desde su
    ciclo anterior, que es la coalescencia natural bajo congestión: cuanto más
    se retrasa la interfaz, más texto recoge por vuelta, no más eventos.

    El techo de memoria ya lo impone `LLMSessionManager._accept_chunk` sobre el
    total de la respuesta, así que este buffer no necesita uno propio: solo
    retiene lo que aún no se ha pintado.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # dict conserva el orden de llegada de cada petición.
        self._por_peticion: dict[int, list[str]] = {}

    def append(self, request_id: int, text: str) -> None:
        """Añade un fragmento. Llamado desde el hilo de trabajo; no bloquea."""
        if not text:
            return
        with self._lock:
            self._por_peticion.setdefault(request_id, []).append(text)

    def take(self, request_id: int) -> str:
        """Extrae y coalesce lo pendiente de una petición."""
        with self._lock:
            partes = self._por_peticion.pop(request_id, None)
        return "".join(partes) if partes else ""

    def take_all(self) -> list[tuple[int, str]]:
        """Extrae todo lo pendiente, coalescido y en orden de llegada."""
        with self._lock:
            pendiente = self._por_peticion
            self._por_peticion = {}
        return [(request_id, "".join(partes)) for request_id, partes in pendiente.items() if partes]

    def discard(self, request_id: int) -> None:
        """Descarta lo pendiente de una petición cancelada."""
        with self._lock:
            self._por_peticion.pop(request_id, None)

    def clear(self) -> None:
        """Descarta todo lo pendiente."""
        with self._lock:
            self._por_peticion.clear()

    def pending_requests(self) -> int:
        """Número de peticiones con texto sin pintar (diagnóstico y pruebas)."""
        with self._lock:
            return len(self._por_peticion)
