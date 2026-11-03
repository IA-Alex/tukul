"""El llavero no se consulta en el hilo de Tk.

Leer el llavero puede tardar (D-Bus/Secret Service en Linux, diálogo de acceso
en macOS). Antes, `app.key` y el diálogo de configuración lo leían directamente
en el hilo de Tk y congelaban la ventana. Ahora la lectura va a un hilo daemon y
el resultado se publica en una caché; nadie llama a Tk desde ese hilo.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_core import storage
from tukul_ui.app import KEYRING_TIMEOUT_SECONDS, TukulApp

CLAVE = "CLAVE_PRUEBA_KEYRING"


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestKeyringFueraDelHiloTk(unittest.TestCase):
    """La key del llavero llega sin bloquear el bucle de eventos."""

    def setUp(self):
        # Estos tests verifican CÓMO se lee el llavero, no si el runner tiene
        # backend. En CI (sin Secret Service) hay que simular uno disponible;
        # de lo contrario la app acierta al no lanzar la lectura y el test
        # mediría otra cosa.
        self._backend_original = storage.credential_backend_disponible
        storage.credential_backend_disponible = lambda: True
        self.addCleanup(lambda: setattr(
            storage, "credential_backend_disponible", self._backend_original))

        self.directorio = tempfile.TemporaryDirectory()
        raiz = Path(self.directorio.name)
        self.documento = raiz / "articulo.md"
        self.documento.write_text("texto", encoding="utf-8")
        config = raiz / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
            'provider = "openai_compatible"\n'
            'endpoint = "https://api.example.com/v1/chat/completions"\n'
            'model = "m"\napi_key_env = "' + CLAVE + '"\n',
            encoding="utf-8")
        # Sin variable de entorno: obliga a usar el llavero.
        os.environ.pop(CLAVE, None)
        self.app = TukulApp(config)
        self.app.load_document(self.documento)
        self.app.update()

    def tearDown(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass  # Un test ya la cerró para comprobar el apagado.
        self.directorio.cleanup()
        os.environ.pop(CLAVE, None)

    def test_la_propiedad_key_no_llama_al_llavero(self):
        with patch.object(storage, "load_key", side_effect=AssertionError("bloquea Tk")):
            self.assertEqual(self.app.key, "")

    def test_la_lectura_no_ocurre_en_el_hilo_de_tk(self):
        """Pedir la key desde la interfaz solo dispara la lectura, no la espera."""
        hilo_lectura: list[str] = []
        liberado = threading.Event()

        def load_key_lento(_perfil: str) -> str:
            hilo_lectura.append(threading.current_thread().name)
            liberado.wait(2)
            return "secreto"

        with patch.object(storage, "load_key", side_effect=load_key_lento):
            inicio = time.monotonic()
            self.assertEqual(self.app._resolver_credenciales(), "")
            self.assertLess(time.monotonic() - inicio, 0.2,
                            "La interfaz no debe esperar al llavero")
            limite = time.monotonic() + 2
            while not hilo_lectura and time.monotonic() < limite:
                self.app.update()
                time.sleep(0.01)
            liberado.set()
        self.assertIn("keyring-p", hilo_lectura,
                      "La lectura debe ocurrir en su propio hilo")

    def test_el_worker_recibe_la_key_del_llavero(self):
        """El envío real resuelve la key dentro del worker, sin bloquear Tk."""
        with patch.object(storage, "load_key", return_value="desde-llavero"):
            self.assertEqual(self.app._esperar_key(), "desde-llavero")

    def test_no_queda_hilo_de_keyring_vivo_tras_cerrar(self):
        """La ventana no debe destruirse con una lectura del llavero en curso.

        Un hilo vivo que asigna memoria durante el cierre puede hacer que el
        recolector destruya variables Tk desde él (`Variable.__del__` fuera del
        hilo principal). destroy() espera a los hilos de keyring con un tope.
        """
        liberado = threading.Event()

        def load_key_lento(_perfil: str) -> str:
            liberado.wait(2)
            return "secreto"

        with patch.object(storage, "load_key", side_effect=load_key_lento):
            self.app._resolver_credenciales()
            self.assertTrue(self.app._llaves_en_curso, "La lectura debe haber empezado")
            # Se libera mientras destroy() espera: así se mide el apagado, no
            # el tope de espera (que tiene su propia prueba).
            threading.Timer(0.05, liberado.set).start()
            self.app.destroy()
            self.assertFalse(self.app._llaves_en_curso,
                             "Al cerrar no debe quedar una lectura pendiente")

    def test_el_resultado_queda_en_cache_y_se_sirve_sin_releer(self):
        with patch.object(storage, "load_key", return_value="desde-llavero") as leer:
            self.assertEqual(self.app._esperar_key(), "desde-llavero")
            leer.assert_called_once()
        with patch.object(storage, "load_key", side_effect=AssertionError("relee")):
            self.assertEqual(self.app.key, "desde-llavero")

    def test_la_espera_tiene_tope(self):
        """Un llavero colgado no deja el envío esperando para siempre."""
        liberado = threading.Event()

        def colgado(_perfil: str) -> str:
            liberado.wait(5)
            return "tarde"

        with patch.object(storage, "load_key", side_effect=colgado):
            # La lectura ya está en marcha (en su hilo) y no terminará a tiempo.
            self.app._prime_key()
            inicio = time.monotonic()
            self.app._esperar_key(timeout=0.2)
            transcurrido = time.monotonic() - inicio
            liberado.set()
        self.assertLess(transcurrido, 1.0, "El tope debe aplicarse de verdad")

    def test_la_session_key_prevalece_sobre_el_llavero(self):
        self.app._add_session_key("p", "de-sesion")
        with patch.object(storage, "load_key", side_effect=AssertionError("no debe leer")):
            self.assertEqual(self.app.key, "de-sesion")


if __name__ == "__main__":
    unittest.main()
