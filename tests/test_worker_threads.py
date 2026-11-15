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

from tukul_ui.worker_threads import WorkerThreads, publicar_en_hilo_ui


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


class TestPublicarEnHiloUI:
    """Guardas de `publicar_en_hilo_ui` (corrección DF-002, hallazgo Alto).

    El contrato `0.7.0` exige «guardas de cierre en cada `after(0, …)` desde
    workers». El helper se ejercitaba solo de forma indirecta desde
    `test_app_ramas.py`/`test_threat_feed_ui.py`; esta sección fija sus
    contratos propios para que un cambio en los cuatro caminos de guarda no
    dependa de que otra prueba lo note.
    """

    def test_programa_el_callback_y_devuelve_true(self):
        from unittest.mock import MagicMock

        host = MagicMock(closing=False)
        callback = MagicMock()

        assert publicar_en_hilo_ui(host, callback) is True
        host.after.assert_called_once_with(0, callback)
        callback.assert_not_called()  # `after` lo ejecutará; aquí solo se programa.

    def test_descarta_si_la_ventana_esta_cerrando(self):
        """Sin esta guarda, un worker tardío publicaba sobre Tk ya cerrándose."""
        from unittest.mock import MagicMock

        host = MagicMock(closing=True)
        callback = MagicMock()

        assert publicar_en_hilo_ui(host, callback) is False
        host.after.assert_not_called()

    def test_un_host_de_tk_ya_cerrado_no_propaga_la_excepcion(self):
        """La guarda de `TclError` envuelve `after`; se prueba por su frontera.

        En esta plataforma Tk responde `after#N` incluso con el intérprete
        cerrado, así que el `TclError` no se puede provocar de forma fiel desde
        Python: el caso real es el de CPython 3.13 documentado en el módulo
        (interprete destruido durante la recolección). Se fija el contrato
        observable del guard —cualquier `TclError` de `after` se convierte en
        `False` con aviso— en vez de simular un Tk roto que no ocurre aquí.
        """
        import tkinter as tk
        from unittest.mock import MagicMock

        host = MagicMock(closing=False)
        host.after.side_effect = tk.TclError("bad window path name")
        logger = MagicMock()

        assert publicar_en_hilo_ui(host, lambda: None, logger) is False
        logger.debug.assert_called_once()

    def test_sobrevive_a_un_runtime_error_de_hilo(self):
        """`RuntimeError` («main thread is not in main loop») no debe escapar."""
        from unittest.mock import MagicMock

        host = MagicMock(closing=False)
        host.after.side_effect = RuntimeError("main thread is not in main loop")
        logger = MagicMock()

        assert publicar_en_hilo_ui(host, lambda: None, logger) is False
        logger.debug.assert_called_once()

    def test_sin_logger_no_falla_al_descartar(self):
        """El logger es opcional: los `Toplevel` de `dialogs.py` no lo pasan."""
        from unittest.mock import MagicMock

        host = MagicMock(closing=False)
        host.after.side_effect = RuntimeError("sin bucle principal")

        assert publicar_en_hilo_ui(host, lambda: None) is False
