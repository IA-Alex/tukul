"""Registro de los hilos de trabajo de la interfaz.

Existe por un fallo real: un worker `daemon` que sobrevivía al `destroy()` de
Tk y llamaba a `logging` desde un hilo sin intérprete Tcl abortaba el proceso
entero (`Fatal Python error: Aborted`) en vez de registrar un error. Se
reprodujo en la suite al añadir un servidor HTTP que mantenía vivo el ciclo de
hilos. Este módulo centraliza el arranque, la espera y el recorte tras `fork`.
"""

from __future__ import annotations

import threading
import time

from tukul_ui.worker_threads import WorkerThreads


class TestRegistroDeWorkers:
    def test_start_devuelve_el_hilo_y_lo_quita_al_terminar(self):
        hecho = threading.Event()

        def trabajo() -> None:
            hecho.set()

        hilo = WorkerThreads.start(trabajo)
        assert hilo.daemon
        assert hecho.wait(5)
        hilo.join(5)
        assert hilo not in WorkerThreads.vivos()

    def test_vivos_solo_devuelve_los_que_siguen_ejecutandose(self):
        liberar = threading.Event()
        hilo = WorkerThreads.start(liberar.wait)
        try:
            assert hilo in WorkerThreads.vivos()
        finally:
            liberar.set()
            hilo.join(5)
        assert hilo not in WorkerThreads.vivos()

    def test_esperar_respeta_el_tope_global(self):
        liberar = threading.Event()
        hilos = [WorkerThreads.start(liberar.wait) for _ in range(3)]
        inicio = time.monotonic()
        vivos = WorkerThreads.esperar(0.4)
        transcurrido = time.monotonic() - inicio
        try:
            # El tope es total, no por hilo: tres hilos no esperan 1,2 s.
            assert transcurrido < 1.5
            assert set(vivos) >= set(hilos)
        finally:
            liberar.set()
            for hilo in hilos:
                hilo.join(5)

    def test_esperar_termina_los_hilos_que_acaban_a_tiempo(self):
        hilos = [WorkerThreads.start(lambda: None) for _ in range(2)]
        WorkerThreads.esperar(5)
        assert all(not hilo.is_alive() for hilo in hilos)
        assert not set(hilos) & set(WorkerThreads.vivos())

    def test_los_hilos_terminados_no_se_acumulan_en_el_registro(self):
        """Regresión: `_workers` crecía sin techo con cada worker terminado.

        `vivos()` los filtraba al devolver, pero el set conservaba la
        referencia para siempre: en una sesión larga, memoria que solo crece.
        Ahora `vivos()` poda los terminados.
        """
        import tukul_ui.worker_threads as modulo

        for _ in range(5):
            WorkerThreads.start(lambda: None)
        WorkerThreads.esperar(5)
        # Tras drenar todos, el registro no debe conservar referencias muertas.
        assert modulo._workers == set(), (
            "Los hilos terminados deben podarse del registro, no solo filtrarse."
        )

    def test_reset_aisla_el_estado_global_entre_pruebas(self):
        """Regresión del flake: un doble inyectado contaminaba la prueba siguiente.

        Varias pruebas parchean `threading.Thread` con un doble; queda
        registrado y, como `MagicMock.is_alive()` es verdadero, sobrevivía a su
        prueba. Una comprobación posterior de «no hay hilos vivos» fallaba
        según el orden. `reset()` corta esa contaminación.
        """
        from unittest.mock import MagicMock

        doble = MagicMock()
        doble.is_alive.return_value = True
        import tukul_ui.worker_threads as modulo

        with modulo._lock:
            modulo._workers.add(doble)
        assert doble in WorkerThreads.vivos()

        WorkerThreads.reset()
        assert WorkerThreads.vivos() == []

    def test_el_hijo_de_un_fork_no_hereda_hilos_muertos(self):
        """Tras `fork()` el niño solo tiene un hilo: el registro debe vaciarse."""
        import os

        liberar = threading.Event()
        WorkerThreads.start(liberar.wait)
        try:
            lectura, escritura = os.pipe()
            pid = os.fork()
            if pid == 0:  # pragma: no cover - proceso hijo
                try:
                    os.write(escritura, str(len(WorkerThreads.vivos())).encode())
                finally:
                    os._exit(0)
            os.close(escritura)
            with os.fdopen(lectura) as fichero:
                heredados = int(fichero.read() or "0")
            os.waitpid(pid, 0)
            assert heredados == 0
        finally:
            liberar.set()
