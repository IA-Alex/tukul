"""Diagnóstico de perfiles LLM: un campo mal tipado no puede pasar en silencio.

`_coerce_profile_fields` descartaba los campos con el tipo equivocado y el
perfil arrancaba con los valores por defecto del dataclass. El usuario veía
"Configura un perfil LLM y una key" con un `config.toml` que parecía correcto
y `--health` respondía "1 perfil habilitado". El log ni siquiera lo mencionaba,
porque la construcción del dataclass no fallaba.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_core import health, storage


def _config(texto: str, directorio: str) -> Path:
    ruta = Path(directorio) / "config.toml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


class TestCamposDescartados(unittest.TestCase):
    """Cada campo ignorado queda registrado con perfil, campo y valor."""

    def tearDown(self) -> None:
        storage.DISCARDED_PROFILE_FIELDS.clear()

    def test_float_entero_se_acepta_como_entero(self):
        """`4096.0` es lo que escribe un editor al tocar un entero: se acepta."""
        with tempfile.TemporaryDirectory() as directorio:
            ruta = _config(
                '[profiles.p]\nprovider = "openai_compatible"\nendpoint = "https://x.test"\n'
                'model = "m"\nmax_output_tokens = 4096.0\n',
                directorio,
            )
            perfiles, _ = storage.load_profiles(ruta)
        self.assertEqual(perfiles["p"].max_output_tokens, 4096)
        self.assertEqual(storage.DISCARDED_PROFILE_FIELDS, [])

    def test_texto_en_un_entero_se_registra_y_no_rompe_el_arranque(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = _config(
                '[profiles.p]\nprovider = "openai_compatible"\nendpoint = "https://x.test"\n'
                'model = "m"\nmax_output_tokens = "4096"\n',
                directorio,
            )
            perfiles, _ = storage.load_profiles(ruta)
        # El perfil existe (no desaparece) con el valor por defecto…
        self.assertIn("p", perfiles)
        self.assertEqual(perfiles["p"].max_output_tokens, 1000)
        # …y el descarte es visible, con el valor recibido.
        self.assertEqual(len(storage.DISCARDED_PROFILE_FIELDS), 1)
        detalle = storage.DISCARDED_PROFILE_FIELDS[0]
        self.assertIn("perfiles.p.max_output_tokens", detalle)
        self.assertIn("'4096'", detalle)

    def test_booleano_en_un_numero_se_rechaza(self):
        """En Python `True` es un `int`: sin esta guarda sería max_output_tokens=1."""
        with tempfile.TemporaryDirectory() as directorio:
            ruta = _config(
                '[profiles.p]\nprovider = "openai_compatible"\nmax_output_tokens = true\n',
                directorio,
            )
            perfiles, _ = storage.load_profiles(ruta)
        self.assertEqual(perfiles["p"].max_output_tokens, 1000)
        self.assertIn("booleano", storage.DISCARDED_PROFILE_FIELDS[0])

    def test_provider_no_texto_se_registra(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = _config("[profiles.p]\nprovider = 123\n", directorio)
            storage.load_profiles(ruta)
        self.assertTrue(
            any("perfiles.p.provider" in d for d in storage.DISCARDED_PROFILE_FIELDS)
        )

    def test_una_lectura_limpia_limpia_los_avisos_anteriores(self):
        with tempfile.TemporaryDirectory() as directorio:
            storage.load_profiles(_config("[profiles.p]\nprovider = 1\n", directorio))
            self.assertTrue(storage.DISCARDED_PROFILE_FIELDS)
            storage.load_profiles(_config("[profiles.p]\nprovider = \"disabled\"\n", directorio))
        self.assertEqual(storage.DISCARDED_PROFILE_FIELDS, [])


class TestHealthExplicaLosCamposDescartados(unittest.TestCase):
    """`--health` debe decir POR QUÉ el perfil no usa lo que el TOML declara."""

    def tearDown(self) -> None:
        storage.DISCARDED_PROFILE_FIELDS.clear()

    def test_health_sin_descartes_no_añade_ruido(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = _config(
                '[profiles.p]\nprovider = "openai_compatible"\nendpoint = "https://x.test"\n'
                'model = "m"\n',
                directorio,
            )
            estado = health.check_health(ruta)
        estado_comp, mensaje = estado.components["llm"]
        self.assertEqual(estado_comp, health.ComponentStatus.HEALTHY)
        self.assertNotIn("ignorado", mensaje)
        # El diagnóstico mantiene sus componentes históricos.
        self.assertNotIn("config", estado.components)

    def test_health_avisa_y_cita_el_campo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = _config(
                '[profiles.p]\nprovider = "openai_compatible"\nendpoint = "https://x.test"\n'
                'model = "m"\nmax_context_chars = "mucho"\n',
                directorio,
            )
            estado = health.check_health(ruta)
        estado_comp, mensaje = estado.components["llm"]
        self.assertEqual(estado_comp, health.ComponentStatus.WARNING)
        self.assertTrue(mensaje.startswith("1 perfil(es) habilitado(s)"))
        self.assertIn("1 campo(s) ignorado(s)", mensaje)
        self.assertIn("max_context_chars", mensaje)
        # Un campo ignorado no convierte una instalación usable en inservible.
        self.assertFalse(estado.has_errors)

    def test_health_sigue_leyendo_la_configuracion_una_sola_vez(self):
        with patch.object(storage, "load_profiles", wraps=storage.load_profiles) as leer:
            health.check_health()
        self.assertEqual(leer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
