"""Guardas de apagado: la suite no debe terminar con hilos vivos.

Encontrarlo tarde es caro: un hilo que sigue asignando memoria al final puede
hacer que el recolector destruya variables Tk desde él y el error aparece
atribuido a un test posterior, intermitentemente (`Variable.__del__` →
`main thread is not in main loop`). Esta guarda convierte ese ruido aleatorio
en un fallo determinista y localizado.
"""
from __future__ import annotations

import threading

import pytest

# Hilos de trabajo legítimos que pueden sobrevivir a un test (son daemon y sin
# efecto sobre Tk); cualquier otro vive lo suficiente para auditarse.
_HILOS_IGNORADOS = ("MainThread",)


def _hilos_sospechosos() -> list[str]:
    return [t.name for t in threading.enumerate()
            if t.name not in _HILOS_IGNORADOS and t.is_alive()]


@pytest.fixture(autouse=True)
def _sin_hilos_colgados_al_terminar():
    """Falla el test que deja un hilo propio vivo y ya no en ejecución temporal.

    Se comprueba después de cada test: un hilo del keyring de la app anterior
    debe haber terminado o estar esperando su tope, no acumularse entre tests.
    """
    yield
    # Margen para que los hilos programados por el test terminen por sí solos.
    for _hilo in list(threading.enumerate()):
        if _hilo.name in _HILOS_IGNORADOS or not _hilo.is_alive():
            continue
        _hilo.join(timeout=0.05)
    pendientes = [nombre for nombre in _hilos_sospechosos()
                  if nombre.startswith("keyring")]
    assert not pendientes, f"Quedaron hilos de keyring vivos: {pendientes}"
