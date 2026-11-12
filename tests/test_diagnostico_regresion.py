"""Regresiones de la auditoría estructural — diagnóstico y logging.

Dividido de `test_auditoria_regresion.py` (1.544 líneas, 22 clases mezclando
dominios) por dominio. Cada prueba ejecuta código de producción: si se revierte
la corrección, la prueba falla.
"""
import io
import os
import queue
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from _regresion_helpers import (
    HAS_DISPLAY,
    _display_available,
    _esperar_hilo_de_envio,
    _headless_app,
)

from tukul_core import storage
from tukul_core.llm import LLMClient, LlmError, validate_endpoint
from tukul_core.models import ArticleSession, LlmProfile
from tukul_ui.app import TukulApp
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import EstadoUI


class TestSaludDeLaInstalacion(unittest.TestCase):
    def test_instalacion_nueva_tiene_avisos_pero_no_errores(self):
        from tukul_core import health

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(storage, "CONFIG_PATH", Path(directory) / "nada" / "config.toml"):
                status = health.check_health()

        self.assertFalse(status.is_healthy, "Sin perfiles hay avisos")
        self.assertFalse(status.has_errors, "…pero nada roto: --health debe salir con 0")

    def test_el_primer_arranque_indica_el_siguiente_paso(self):
        """Los dos avisos de una instalación virgen se leen como un paso a dar.

        Antes la salida decía `ISSUES` con dos ausencias técnicas y se leía
        como «está roto». Ahora conserva el estado (aviso, no error) pero añade
        el paso concreto y la ruta a la que copiar el config.
        """
        from tukul_core import health

        with tempfile.TemporaryDirectory() as directory:
            destino = Path(directory) / "nada" / "config.toml"
            with patch.object(storage, "CONFIG_PATH", destino):
                texto = health.status_string()

        self.assertIn("SIN CONFIGURAR", texto)
        self.assertNotIn("ISSUES", texto, "Un primer arranque no está «roto»")
        self.assertIn("siguiente paso: copia tukul.example.toml", texto)
        self.assertIn(str(destino), texto, "Debe nombrar la MISMA ruta que inspeccionó")
        self.assertIn("tu API key", texto)

    def test_el_diagnostico_no_deja_archivos_en_la_carpeta_de_config(self):
        """`--health` no crea artefactos en el directorio del usuario.

        Hallazgo DF-004: `_check_storage` probaba la escritura con un
        NamedTemporaryFile DENTRO de la carpeta de config. Ahora comprueba el
        permiso sin crear nada.
        """
        from tukul_core import health

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
                'provider = "openai_compatible"\nendpoint = "https://x/v1"\n'
                'model = "m"\napi_key_env = "K"\n',
                encoding="utf-8",
            )
            con_permiso = Path(directory).stat().st_mode
            with patch.object(storage, "CONFIG_PATH", config):
                estado, detalle = health._check_storage(None, config)

            self.assertEqual(estado, health.ComponentStatus.HEALTHY, detalle)
            # Lo único en la carpeta es el config que creamos nosotros.
            assert [p.name for p in Path(directory).iterdir()] == ["config.toml"]
            assert Path(directory).stat().st_mode == con_permiso

    def test_una_instalacion_configurada_no_muestra_el_siguiente_paso(self):
        from tukul_core import health

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
                'provider = "openai_compatible"\nendpoint = "https://x/v1"\n'
                'model = "m"\napi_key_env = "K"\n',
                encoding="utf-8",
            )
            with patch.object(storage, "CONFIG_PATH", config):
                texto = health.status_string()

        self.assertNotIn("siguiente paso", texto)
        self.assertIn("1 perfil(es) habilitado(s)", texto)

    def test_un_error_no_se_presenta_como_primer_arranque(self):
        """Si algo está roto de verdad no se invita a «copia el ejemplo»."""
        from tukul_core import health
        from tukul_core.health import ComponentStatus, HealthStatus

        status = HealthStatus(
            is_healthy=False,
            components={
                "storage": (ComponentStatus.ERROR, "La carpeta de config es de solo lectura"),
                "llm": (ComponentStatus.WARNING, "Ninguno configurado todavía"),
            },
            timestamp="2026-11-05T00:00:00",
            config_path="/tmp/config.toml",
        )
        self.assertEqual(health._siguiente_paso(status), "")

    def test_un_error_real_sigue_diciendo_issues(self):
        """El rótulo distingue «roto» de «sin configurar»."""
        from tukul_core import health
        from tukul_core.health import ComponentStatus, HealthStatus

        roto = HealthStatus(
            is_healthy=False,
            components={
                "storage": (ComponentStatus.ERROR, "La carpeta de config es de solo lectura"),
                "llm": (ComponentStatus.HEALTHY, "1 perfil(es) habilitado(s)"),
            },
            timestamp="2026-11-05T00:00:00",
        )
        self.assertIn("Salud: ISSUES", health.status_string(roto))

    def test_avisos_sin_primer_arranque_se_rotulan_avisos(self):
        from tukul_core import health
        from tukul_core.health import ComponentStatus, HealthStatus

        aviso_suelto = HealthStatus(
            is_healthy=False,
            components={
                "storage": (ComponentStatus.HEALTHY, "OK"),
                "llm": (ComponentStatus.WARNING, "Ninguno configurado todavía"),
            },
            timestamp="2026-11-05T00:00:00",
        )
        texto = health.status_string(aviso_suelto)
        self.assertIn("Salud: AVISOS", texto)
        self.assertNotIn("ISSUES", texto)

    def test_un_estado_sin_componentes_no_inventa_pista(self):
        from tukul_core import health
        from tukul_core.health import HealthStatus

        status = HealthStatus(is_healthy=True, components={}, timestamp="2026-11-05T00:00:00")
        self.assertEqual(health._siguiente_paso(status), "")

    def test_directorio_de_config_no_escribible_es_error(self):
        from tukul_core.health import ComponentStatus, check_health

        with tempfile.TemporaryDirectory() as directory:
            solo_lectura = Path(directory) / "cfg"
            solo_lectura.mkdir()
            os.chmod(solo_lectura, 0o500)
            try:
                with patch.object(storage, "CONFIG_PATH", solo_lectura / "config.toml"):
                    status = check_health()
                self.assertEqual(status.components["storage"][0], ComponentStatus.ERROR)
                self.assertTrue(status.has_errors)
            finally:
                os.chmod(solo_lectura, 0o700)

    def test_check_health_diagnostica_el_config_indicado_no_el_por_defecto(self):
        from tukul_core.health import check_health

        with tempfile.TemporaryDirectory() as directory:
            propio = Path(directory) / "propio.toml"
            perfiles = "\n".join(
                f'[profiles.p{i}]\nprovider = "openai_compatible"\n'
                f'endpoint = "https://x.example/v1/chat/completions"\nmodel = "m{i}"'
                for i in range(3)
            )
            propio.write_text(f'[llm]\nactive_profile = "p0"\n\n{perfiles}\n', encoding="utf-8")

            status = check_health(propio)

            self.assertEqual(status.config_path, str(propio))
            self.assertIn("3 perfil(es) habilitado(s)", status.components["llm"][1])

    def test_status_string_declara_el_archivo_inspeccionado(self):
        from tukul_core.health import check_health, status_string

        with tempfile.TemporaryDirectory() as directory:
            propio = Path(directory) / "propio.toml"
            propio.write_text("[llm]\n", encoding="utf-8")

            texto = status_string(check_health(propio))

            self.assertIn(str(propio), texto)

    def test_la_cli_pasa_config_al_diagnostico(self):
        import subprocess

        raiz = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as directory:
            propio = Path(directory) / "cli.toml"
            perfiles = "\n".join(
                f'[profiles.p{i}]\nprovider = "openai_compatible"\n'
                f'endpoint = "https://x.example/v1/chat/completions"\nmodel = "m{i}"'
                for i in range(2)
            )
            propio.write_text(f'[llm]\nactive_profile = "p0"\n\n{perfiles}\n', encoding="utf-8")

            proceso = subprocess.run(
                [sys.executable, "tukul.py", "--config", str(propio), "--health"],
                cwd=raiz, capture_output=True, text=True, timeout=60,
            )

            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            self.assertIn(str(propio), proceso.stdout)
            self.assertIn("2 perfil(es) habilitado(s)", proceso.stdout)

    def test_check_health_lee_la_configuracion_una_sola_vez(self):
        from tukul_core import health

        with patch.object(storage, "load_profiles", wraps=storage.load_profiles) as leer:
            health.check_health()
        self.assertEqual(leer.call_count, 1, "Se parseaba config.toml dos veces")

class TestLogging(unittest.TestCase):
    def test_health_y_config_validator_usan_el_logger_de_la_app(self):
        from tukul_core import config_validator, health
        from tukul_core.logging_config import LOGGER_NAME

        self.assertEqual(health.logger.name, LOGGER_NAME)
        self.assertEqual(config_validator.logger.name, LOGGER_NAME)
        self.assertTrue(health.logger.handlers, "Sin handlers no llega al log JSON")

    def test_setup_logging_honra_una_ruta_explicita(self):
        from tukul_core.logging_config import setup_logging

        with tempfile.TemporaryDirectory() as directory:
            deseada = Path(directory) / "sub" / "propio.log"
            logger = setup_logging(deseada)
            try:
                efectivas = [
                    Path(h.baseFilename) for h in logger.handlers if hasattr(h, "baseFilename")
                ]
                self.assertIn(deseada, efectivas, "El parámetro log_path se ignoraba")
                self.assertTrue(deseada.exists())
            finally:
                setup_logging(Path(directory) / "descartable.log")

    def test_el_diagnostico_no_declara_sano_un_log_inexistente(self):
        """El chequeo anterior solo comprobaba que logger.debug() no lanzara.

        Con handler de consola presente nunca lanza, así que un destino de log
        imposible (sistema de archivos de solo lectura) se reportaba como «OK».
        """
        import subprocess

        raiz = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as directory:
            hogar = Path(directory) / "hogar"
            hogar.mkdir()
            os.chmod(hogar, 0o500)  # sin permiso de escritura
            try:
                entorno = {**os.environ, "HOME": str(hogar)}
                proceso = subprocess.run(
                    [sys.executable, "tukul.py", "--health"],
                    cwd=raiz, capture_output=True, text=True, timeout=60, env=entorno,
                )
            finally:
                os.chmod(hogar, 0o700)

            self.assertNotIn(
                "logging: ✓", proceso.stdout,
                "El log no pudo crearse; declararlo sano es un falso positivo",
            )
            self.assertIn("logging: ⚠", proceso.stdout)
            self.assertIn("solo consola", proceso.stdout)

    def test_file_logging_status_detecta_un_destino_que_deja_de_escribirse(self):
        from tukul_core.logging_config import file_logging_status, setup_logging

        with tempfile.TemporaryDirectory() as directory:
            destino = Path(directory) / "vivo.log"
            setup_logging(destino)
            try:
                operativo, detalle = file_logging_status()
                self.assertTrue(operativo, detalle)
                self.assertIn(str(destino), detalle)

                # El sistema de archivos puede volverse de solo lectura DESPUÉS
                # del arranque: recordar el error de inicio no bastaría.
                os.chmod(destino, 0o400)
                operativo, detalle = file_logging_status()
                self.assertFalse(operativo)
                self.assertIn("no escribible", detalle)
            finally:
                os.chmod(destino, 0o600)
                setup_logging(Path(directory) / "descartable.log")

    def test_la_rotacion_acota_el_tamano_en_disco(self):
        import logging
        from logging.handlers import RotatingFileHandler

        with tempfile.TemporaryDirectory() as directory:
            destino = Path(directory) / "r.log"
            handler = RotatingFileHandler(destino, maxBytes=512_000, backupCount=2, encoding="utf-8")
            aislado = logging.getLogger("tukul.test.rotacion")
            aislado.propagate = False
            aislado.addHandler(handler)
            aislado.setLevel(logging.INFO)
            try:
                for _ in range(4000):
                    aislado.info("y" * 300)
            finally:
                aislado.removeHandler(handler)
                handler.close()

            familia = list(destino.parent.glob(destino.name + "*"))
            total = sum(f.stat().st_size for f in familia)
            self.assertLessEqual(len(familia), 3, "1 activo + 2 backups")
            self.assertLess(total, 1_600_000, "512KB x 3 es el techo teórico")
