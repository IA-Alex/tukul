"""Resolución y caché de credenciales (API key) de Tukul.

Extraído de `TukulApp` (DF-001): el llavero y su caché son una responsabilidad
propia, con su propio estado mutable compartido entre el hilo de Tk y el hilo
de lectura de keyring. El objeto es dueño del `threading.Lock`, así que el
acceso nunca queda sin sincronizar (DF-016).

La ventana solo aporta tres cosas: el `control_queue` (para avisar de un
llavero ausente), el nombre de la variable de entorno del perfil activo y un
lanzador de hilos. Todo lo demás vive aquí.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from tukul_core import storage

logger = logging.getLogger("tukul")


class CredentialStore:
    """Cachea la API key de cada perfil, leída del llavero en un hilo daemon.

    El llavero (D-Bus/Secret Service, diálogo de macOS) puede tardar; leerlo en
    el hilo de Tk congelaba la interfaz. La lectura se hace en segundo plano y
    el resultado se cachea: el hilo de Tk solo consulta valores ya conocidos.
    """

    def __init__(self, *, arrancar: Callable[[Callable[[], Any], str], Any],
                 avisar_llavero_ausente: Callable[[str], None]) -> None:
        self._arrancar = arrancar
        self._avisar_llavero_ausente = avisar_llavero_ausente
        self._cache: dict[str, str] = {}
        self._en_curso: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ─── Lecturas (hilo de Tk o worker) ─────────────────────────────────────

    def conocido(self, perfil: str) -> bool:
        """¿Ya hay un valor (aunque sea vacío) cacheado para el perfil?"""
        with self._lock:
            return perfil in self._cache

    def valor(self, perfil: str) -> str:
        """Valor cacheado del llavero para el perfil (vacío si no hay)."""
        with self._lock:
            return self._cache.get(perfil, "")

    def guardar(self, perfil: str, valor: str) -> None:
        """Inserta/actualiza el valor cacheado (seguro desde cualquier hilo)."""
        with self._lock:
            self._cache[perfil] = valor

    def en_curso(self, perfil: str) -> bool:
        """¿Hay una lectura del llavero en marcha para ese perfil?"""
        with self._lock:
            return perfil in self._en_curso

    def pendientes(self) -> list[threading.Event]:
        """Señales de las lecturas en curso (para esperarlas en el cierre)."""
        with self._lock:
            return list(self._en_curso.values())

    # ─── Arranque y espera ──────────────────────────────────────────────────

    def precargar(self, perfil: str) -> None:
        """Lanza la lectura del llavero en un worker daemon y guarda el resultado.

        Usa `threading.Event` como futuro: quien pueda bloquear (un worker)
        espera con `esperar`; la interfaz solo consulta la caché.
        """
        # Sin backend de sistema no se lanza el hilo: en CI/contenedor la
        # lectura puede abortar el proceso en lugar de devolver un error.
        if not storage.credential_backend_disponible():
            self.guardar(perfil, "")
            return
        listo = threading.Event()
        with self._lock:
            self._en_curso[perfil] = listo

        def leer() -> None:
            try:
                valor = storage.load_key(perfil)
            except storage.KeyringUnavailableError:
                # El llavero existe pero no responde: NO es «no hay key». Se
                # cachea vacío para no reintentar en bucle, pero se avisa en la
                # barra; si no, el usuario leería «Configura una key», pista falsa.
                self._avisar_llavero_ausente(perfil)
                valor = ""
            except Exception as error:
                # Un llavero ajeno (D-Bus, backend del SO) no debe romper la UI,
                # pero tampoco puede degradar a «sin key» en silencio: antes un
                # fallo distinto de «no existe entrada» se confundía con «no hay
                # key» y enviaba al usuario a «Configura una key», pista falsa.
                # Se registra el fallo (sin volcar el valor) y se avisa igual que
                # cuando el llavero no responde.
                logger.warning(
                    "Lectura del llavero para '%s' falló (%s); se trata como "
                    "llavero no disponible.",
                    perfil,
                    type(error).__name__,
                )
                self._avisar_llavero_ausente(perfil)
                valor = ""
            # Marcar antes de publicar: quien espera esa misma señal no debe
            # encontrar todavía su entrada en `_en_curso` ni un instante.
            with self._lock:
                self._cache[perfil] = valor
                self._en_curso.pop(perfil, None)
            listo.set()

        self._arrancar(leer, f"keyring-{perfil}")

    def asegurar(self, perfil: str) -> None:
        """Lanza la lectura si el perfil no está cacheado ni en curso."""
        with self._lock:
            ya = perfil in self._cache or perfil in self._en_curso
        if not ya:
            self.precargar(perfil)

    def esperar(self, perfil: str, timeout: float) -> None:
        """Espera (con tope) a que termine la lectura en curso del perfil."""
        with self._lock:
            listo = self._en_curso.get(perfil)
        if listo is not None:
            listo.wait(timeout)


def resolver_key(perfil_env: str, session_keys: dict[str, str],
                 active_profile: str, llavero: CredentialStore) -> str:
    """API key en vigor: variable de entorno > key de sesión > llavero.

    Función pura salvo la consulta al `CredentialStore` (que ya sirve solo lo
    conocido): el orden de precedencia vive aquí, en un único sitio.
    """
    return (os.environ.get(perfil_env)
            or session_keys.get(active_profile, "")
            or llavero.valor(active_profile))
