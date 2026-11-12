"""Validación del formulario de perfiles: el campo del nombre no acepta la clave.

Defecto observado: la interfaz guardó una clave (`sk-di-…`) en «Variable de
entorno con la key», la escribió en claro en el TOML y dejó el perfil buscando
una variable inexistente. El fallo solo aparecía al enviar el primer mensaje.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core.llm import LlmError
from tukul_ui.dialogs import _validar_endpoint_completo, validate_api_key_env


class TestCampoDeVariableDeEntorno(unittest.TestCase):
    def test_acepta_un_nombre_de_variable(self):
        self.assertEqual(validate_api_key_env("DEEPINFRA_API_KEY"), "DEEPINFRA_API_KEY")
        self.assertEqual(validate_api_key_env("  OPENAI_API_KEY  "), "OPENAI_API_KEY")

    def test_acepta_vacio(self):
        self.assertEqual(validate_api_key_env(""), "")

    def test_rechaza_una_clave_pegada(self):
        with self.assertRaises(LlmError) as ctx:
            validate_api_key_env("sk-di-u2gbmoPcjh84vwsRWT1tFMCsa13gwkzT")
        self.assertIn("NOMBRE de una variable", str(ctx.exception))
        self.assertIn("API key", str(ctx.exception))

    def test_rechaza_valores_que_no_son_un_nombre(self):
        for valor in ("clave con espacios", "x" * 80):
            with self.subTest(valor=valor[:20]), self.assertRaises(LlmError):
                validate_api_key_env(valor)


class TestEndpointCompleto(unittest.TestCase):
    def test_rechaza_la_base_sin_la_ruta_de_chat(self):
        with self.assertRaises(LlmError) as ctx:
            _validar_endpoint_completo("deepinfra", "https://api.deepinfra.com/v1/openai")
        self.assertIn("/chat/completions", str(ctx.exception))

    def test_acepta_la_ruta_completa(self):
        _validar_endpoint_completo(
            "deepinfra", "https://api.deepinfra.com/v1/openai/chat/completions")

    def test_no_opina_sobre_endpoints_personalizados(self):
        _validar_endpoint_completo("openai_compatible", "https://mi.servidor/v1/loco")


class TestEjemploUsaLosProveedoresReales(unittest.TestCase):
    """`tukul.example.toml` debe declarar el id real de cada proveedor.

    Con `provider = "openai_compatible"` en un perfil DeepInfra/Novita se pierde
    la identidad del proveedor: el selector muestra el hint genérico, la
    validación del endpoint base no se aplica y `_validar_endpoint_completo` no
    avisa. El ejemplo es la plantilla que copia el usuario, así que debe reflejar
    lo que la UI ofrece.
    """

    def setUp(self):
        from tukul_core import storage
        storage.DISCARDED_PROFILE_FIELDS.clear()
        raiz = Path(__file__).parent.parent
        self.perfiles, _ = storage.load_profiles(raiz / "tukul.example.toml")

    def tearDown(self):
        from tukul_core import storage
        storage.DISCARDED_PROFILE_FIELDS.clear()

    def test_cada_perfil_declara_un_proveedor_valido(self):
        from tukul_core.llm import PROVIDERS

        for nombre, perfil in self.perfiles.items():
            # `disabled` es el centinela de "sin proveedor", no un id de PROVIDERS.
            if perfil.provider == "disabled":
                continue
            with self.subTest(perfil=nombre):
                self.assertIn(perfil.provider, PROVIDERS)

    def test_los_perfiles_conocidos_usan_su_propio_id(self):
        # El perfil llamado como el proveedor no debe caer al genérico.
        for nombre in ("deepinfra", "novita"):
            if nombre in self.perfiles:
                with self.subTest(perfil=nombre):
                    self.assertEqual(self.perfiles[nombre].provider, nombre)

    def test_su_endpoint_es_una_ruta_de_chat_completa(self):
        """El ejemplo no debe traer la base del proveedor sin la ruta de chat."""
        for nombre, perfil in self.perfiles.items():
            if perfil.provider in ("deepinfra", "novita"):
                with self.subTest(perfil=nombre):
                    _validar_endpoint_completo(perfil.provider, perfil.endpoint)


if __name__ == "__main__":
    unittest.main()
