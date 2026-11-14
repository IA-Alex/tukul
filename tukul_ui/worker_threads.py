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
import tkinter as tk
from collections.abc import Callable
from typing import Any, Protocol

#: Registro de los hilos de trabajo, para poder esperarlos o descartarlos.
_workers: set[threading.Thread] = set()
_lock = threading.Lock()


class _HostUI(Protocol):
    """Lo mínimo que un host debe exponer para publicar en el hilo de Tk.

    No exige `closing`: algunos llamadores (`dialogs.py`) publican sobre un
    `Toplevel` directo, que no lo declara; ahí se consulta de forma defensiva.
    """

    def after(self, ms: Any, func: Any, *args: Any) -> str: ...


def en_el_hilo_de_tk() -> bool:
    """True si el llamador es el hilo que puede tocar Tcl.

    `after()` desde un worker lanza `RuntimeError: main thread is not in main
    loop` en CPython 3.13, y ese error —surgido durante la recolección de
    basura— puede abortar el proceso entero en lugar de propagarse. Los
    workers son daemon: pueden sobrevivir al cierre y llegar aquí. Mejor no
    programar nada que morir.
    """
    return threading.current_thread() is threading.main_thread()


def publicar_en_hilo_ui(host: _HostUI, callback: Callable[[], Any],
                        logger: object | None = None) -> bool:
    """Programa `callback` en el hilo de Tk sin arriesgar el aborto del proceso.

    Sustituye al patrón disperso `host.after(0, …)` desde un worker, que en
    CPython 3.13 puede lanzar `RuntimeError` al registrar sobre un intérprete
    Tcl ya destruido y —si surge durante la recolección de basura— abortar el
    proceso entero (`Fatal Python error: Aborted`) en vez de propagarse.

    Devuelve True si el callback quedó programado y False si se descartó por
    ventana cerrándose o por fallo de Tk al registrar.
    """
    if getattr(host, "closing", False):
        return False
    try:
        host.after(0, callback)
    except (RuntimeError, tk.TclError):
        # La ventana pudo destruirse entre la comprobación y el `after`: el
        # aviso es informativo y no debe tumbar el intérprete.
        if logger is not None:
            logger.debug("Callback de UI descartado: la ventana ya no existe.")  # type: ignore[attr-defined]
        return False
    return True


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
