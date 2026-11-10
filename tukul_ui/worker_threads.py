"""Hilos que no sobreviven al `fork()` ni abortan el intérprete al morir la UI.

Los workers de petición son `daemon` como red de seguridad, no como mecanismo
normal de parada. Pero un daemon puede sobrevivir al `destroy()` de Tk —cuando
la espera de cierre se agota, por ejemplo— y, al ejecutarse después, llama a
`logging` o a `after()` desde un hilo sin intérprete Tk activo. Eso lanza un
`RuntimeError` que, en CPython 3.13, a veces no se puede capturar: el proceso
se aborta (`Fatal Python error: Aborted`) en vez de registrar un error.

Esto se vio primero en la suite: `tests/test_llm_http_contract.py` levanta un
servidor HTTP y, si un worker de la app moría durante la recolección de basura,
toda la ejecución abortaba.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

#: Registro de los hilos de trabajo, para poder esperarlos o descartarlos.
_workers: set[threading.Thread] = set()
_lock = threading.Lock()


class WorkerThreads:
    """Crea y sigue los hilos de trabajo de la interfaz."""

    @staticmethod
    def start(target: Callable[[], object]) -> threading.Thread:
        """Arranca un worker daemon y lo deja registrado hasta que termina."""
        hilo = threading.Thread(target=target, daemon=True)
        with _lock:
            _workers.add(hilo)
        hilo.start()
        return hilo

    @staticmethod
    def vivos() -> list[threading.Thread]:
        """Trabajadores aún en ejecución (datos para el aviso de cierre).

        Poda los que ya terminaron: sin esto, el registro conserva una
        referencia por cada worker que la sesión haya arrancado (memoria que
        crece sin techo en uso prolongado) y una prueba que pregunte «¿hay
        hilos vivos?» vería dobles ya muertos de pruebas anteriores.
        """
        with _lock:
            _workers.intersection_update(
                hilo for hilo in _workers if hilo.is_alive())
            return list(_workers)

    @staticmethod
    def esperar(timeout: float) -> list[threading.Thread]:
        """Espera hasta `timeout` TOTAL y devuelve los que siguen vivos.

        El tope es global, no por hilo: una petición realmente colgada no puede
        alargar el cierre proporcionalmente al número de workers.
        """
        limite = time.monotonic() + max(0.0, timeout)
        for hilo in WorkerThreads.vivos():
            restante = limite - time.monotonic()
            if restante <= 0:
                break
            hilo.join(timeout=restante)
        return WorkerThreads.vivos()

    @staticmethod
    def _reset_tras_fork() -> None:
        """En el hijo de un `fork()` no existe ningún hilo: no se heredan."""
        global _lock
        _workers.clear()
        _lock = threading.Lock()

    @staticmethod
    def reset() -> None:
        """Vacía el registro. Solo para pruebas: aísla el estado global.

        El registro es estado de módulo; sin vaciarlo, los dobles de worker que
        una prueba inyecta (parcheando `threading.Thread`) quedan «vivos» para
        las siguientes y una comprobación legítima de «no hay hilos» falla por
        contaminación de orden de ejecución.
        """
        with _lock:
            _workers.clear()


# Se registra a nivel de módulo, no en una función de arranque: un `fork()` sin
# `exec` (tests, subprocesos) heredaría el registro con hilos muertos.
try:
    os.register_at_fork(after_in_child=WorkerThreads._reset_tras_fork)
except (AttributeError, OSError):  # pragma: no cover - plataformas sin fork
    pass
