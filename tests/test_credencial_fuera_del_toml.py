"""Persistencia: una credencial nunca llega al TOML, venga de donde venga.

El formulario ya rechaza una clave en `api_key_env`, pero el archivo se escribe
en un único punto (`save_profiles`) al que también llegan scripts, importaciones
y ediciones manuales. La defensa se prueba ahí, sobre el archivo real.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core.models import LlmProfile
from tukul_core.storage import _parece_credencial, load_profiles, save_profiles

CLAVE = "sk-di-u2gbmoPcjh84vwsRWT1tFMCsa13gwkzT"


class TestCredencialFueraDelToml(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "config.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def _perfil(self, api_key_env: str) -> LlmProfile:
        return LlmProfile(
            name="default", provider="deepinfra", endpoint="https://x/v1",
            model="m", api_key_env=api_key_env,
        )

    def test_una_clave_no_se_escribe_en_el_archivo(self):
        save_profiles({"default": self._perfil(CLAVE)}, "default", self.ruta)
        contenido = self.ruta.read_text(encoding="utf-8")
        self.assertNotIn(CLAVE, contenido)
        self.assertNotIn("sk-di-", contenido)

    def test_el_nombre_de_la_variable_si_se_guarda(self):
        save_profiles({"default": self._perfil("DEEPINFRA_API_KEY")}, "default", self.ruta)
        perfiles, _ = load_profiles(self.ruta)
        self.assertEqual(perfiles["default"].api_key_env, "DEEPINFRA_API_KEY")

    def test_el_archivo_sigue_siendo_cargable_tras_el_filtro(self):
        save_profiles({"default": self._perfil(CLAVE)}, "default", self.ruta)
        perfiles, activo = load_profiles(self.ruta)
        self.assertEqual(activo, "default")
        self.assertEqual(perfiles["default"].api_key_env, "")

    def test_reconoce_lo_que_parece_credencial(self):
        self.assertTrue(_parece_credencial(CLAVE))
        self.assertTrue(_parece_credencial("  sk-abc"))
        self.assertFalse(_parece_credencial("DEEPINFRA_API_KEY"))
        self.assertFalse(_parece_credencial("OPENAI_API_KEY"))


if __name__ == "__main__":
    unittest.main()
