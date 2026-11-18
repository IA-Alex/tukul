"""Contratos de las aserciones del eval funcional (promptfoo).

Un eval que no puede fallar no mide nada. Estos tests fijan las dos
propiedades que se rompieron sin que nadie lo notara:

1. `hallazgos_usables.js` aplica `config.maximo`, así que un artículo limpio
   con `maximo: 0` falla si el modelo **inventa** hallazgos. Con la versión
   anterior el control negativo salía en verde (falso PASS medido).
2. Los casos marcados como «artículo limpio» del YAML no contienen erratas: si
   las tuvieran, el modelo acertaría al señalarlas y el caso se leería como
   un fallo del modelo.

No requieren red ni `promptfoo`: se ejecutan con `node`, igual que hace el
runner de promptfoo al cargar una aserción.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ASSERTS = RAIZ / "evals" / "asserts"
CONFIG_FUNCIONAL = RAIZ / "evals" / "promptfooconfig_funcional.yaml"

#: Erratas que estaban en los casos llamados «limpios» y que el modelo detectaba
#: con razón. Si alguna vuelve, el caso deja de medir alucinación.
ERRATAS_PROHIBIDAS = ("procso", "depedencias", "movera", "linpio")


def _hay_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_hay_node(), "node no está instalado")
class TestHallazgosUsables(unittest.TestCase):
    """La aserción acepta lo correcto y rechaza la alucinación, en ambos sentidos."""

    def _evaluar(self, salida: str, maximo: int | None) -> bool:
        """Ejecuta la aserción de JS con un `output` y un `context` reales."""
        guion = """
const fn = require(process.argv[1]);
const salida = process.argv[2];
const maximo = process.argv[3] === 'sin-config' ? undefined : Number(process.argv[3]);
const context = { vars: { article: 'La ciberseguridad es un proceso continuo.' } };
if (maximo !== undefined) context.config = { maximo };
process.stdout.write(String(fn(salida, context)));
"""
        resultado = subprocess.run(
            ["node", "-e", guion, str(ASSERTS / "hallazgos_usables.js"), salida,
             "sin-config" if maximo is None else str(maximo)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return resultado.stdout.strip() == "true"

    @staticmethod
    def _envolver(hallazgos: list[dict]) -> str:
        """Salida tal como la entrega el adaptador: JSON con `output` dentro."""
        return json.dumps({"output": json.dumps({"findings": hallazgos})})

    def _hallazgo(self, original: str) -> dict:
        return {"category": "ortografía", "severity": "alta", "original": original,
                "suggestion": "x", "reason": "y"}

    def test_un_texto_limpio_sin_hallazgos_pasa(self):
        self.assertTrue(self._evaluar(self._envolver([]), 0))

    def test_un_hallazgo_inventado_con_maximo_cero_falla(self):
        """Regresión: el control negativo salía en VERDE con la versión anterior."""
        self.assertFalse(self._evaluar(self._envolver([self._hallazgo("proceso")]), 0))

    def test_varios_hallazgos_inventados_fallan(self):
        self.assertFalse(self._evaluar(
            self._envolver([self._hallazgo("proceso"), self._hallazgo("continuo")]), 0))

    def test_maximo_dos_tolera_dos_y_rechaza_tres(self):
        dos = [self._hallazgo("proceso"), self._hallazgo("continuo")]
        self.assertTrue(self._evaluar(self._envolver(dos), 2))
        self.assertFalse(self._evaluar(
            self._envolver([*dos, self._hallazgo("ciberseguridad")]), 2))

    def test_sin_config_no_limita_el_numero(self):
        self.assertTrue(self._evaluar(self._envolver([self._hallazgo("proceso")]), None))

    def test_un_array_raiz_vacio_es_un_texto_limpio(self):
        """`review._decode_payload` normaliza el array raíz: aquí debe valer igual."""
        self.assertTrue(self._evaluar(json.dumps({"output": "[]"}), 0))

    def test_una_cita_que_no_esta_en_el_articulo_falla(self):
        inventado = self._hallazgo("esto no aparece en el artículo")
        self.assertFalse(self._evaluar(self._envolver([inventado]), 5))


class TestConfiguracionFuncional(unittest.TestCase):
    """Los casos del YAML funcional son coherentes con lo que dicen medir."""

    def test_la_temperatura_del_eval_es_configurable(self):
        """El riesgo residual T=0 vs T=0.5 se mide con la misma batería.

        El adaptador debe aceptar `TUKUL_EVAL_TEMPERATURE` (0 por defecto para el
        eval determinista; 0.5 para el del producto) y sanear valores inválidos
        en vez de romper el eval.
        """
        import os
        import subprocess
        import sys

        adaptador = RAIZ / "evals" / "proveedor_tukul.py"
        guion = (
            "import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('p', {str(adaptador)!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "print(m._temperatura())\n"
        )
        for valor, esperado in (("0", "0.0"), ("0.5", "0.5"), ("basura", "0.0"), ("9", "0.0")):
            entorno = dict(os.environ, TUKUL_EVAL_TEMPERATURE=valor)
            # `sys.executable` es el intérprete que corre esta suite. Con la ruta
            # fija `.venv/bin/python` el test pasaba en local pero fallaba en CI,
            # donde no hay venv en el checkout (FileNotFoundError, runs de 0.8.0).
            resultado = subprocess.run(
                [sys.executable, "-c", guion],
                capture_output=True, text=True, env=entorno, timeout=30, check=True,
            )
            self.assertEqual(resultado.stdout.strip(), esperado,
                             f"TUKUL_EVAL_TEMPERATURE={valor}")

    def setUp(self) -> None:
        self.texto = CONFIG_FUNCIONAL.read_text(encoding="utf-8")

    def test_los_casos_tienen_nombre_reconocible(self):
        """`desripción` (typo) dejaba los casos «(sin nombre)» en el reporte."""
        self.assertNotIn("desripción:", self.texto)
        self.assertEqual(self.texto.count("  - description:"), self.texto.count("  - description:"))

    def test_los_articulos_limpios_no_contienen_erratas(self):
        """Un «limpio» con erratas hace que el modelo acierte y el caso parezca fallo.

        Se mira solo el CONTENIDO de los artículos, no los comentarios: el del
        YAML explica cuáles eran las erratas y debe poder nombrarlas.
        """
        import re

        articulos = re.findall(r"article: \|\n((?:\s{8,}.*\n)+)", self.texto)
        self.assertTrue(articulos, "no se encontró ningún artículo en el YAML")
        limpios = [a for a in articulos if "proceso continuo" in a or "migración de datos" in a]
        self.assertGreaterEqual(len(limpios), 2, "faltan los casos de artículo limpio")
        for articulo in limpios:
            for errata in ERRATAS_PROHIBIDAS:
                self.assertNotIn(errata, articulo, f"«{errata}» sigue en un caso limpio")

    def test_las_asercciones_de_alucinacion_exigen_cero_hallazgos(self):
        """`maximo: 0` es la exigencia real; sin ella el caso solo mira la forma."""
        casos_limpios = self.texto.count("no inventa errores")
        self.assertGreaterEqual(casos_limpios, 2)
        self.assertEqual(self.texto.count("maximo: 0"), casos_limpios)


class TestReintentosDelAdaptador(unittest.TestCase):
    """El adaptador reintenta un proveedor «ocupado» en vez de contarlo como fallo.

    DeepInfra devuelve `429 {"error":{"message":"Model busy, retry later"}}` sin
    `Retry-After` cuando está saturado. Sin reintentos, cada 429 se convierte en
    un fallo del caso y envenena el veredicto: se midió una batería a 9/24 por
    esta causa, no por el contrato. Un 401/403, en cambio, es credencial y NO
    debe reintentarse: se propaga como `CredencialInvalidaError`.
    """

    def _cargar_adaptador(self):
        import importlib.util

        adaptador = RAIZ / "evals" / "proveedor_tukul.py"
        spec = importlib.util.spec_from_file_location("proveedor_tukul_test", adaptador)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_un_429_seguido_de_200_reintenta_y_devuelve_la_respuesta(self):
        """El caso central: el proveedor está ocupado y luego responde."""
        from unittest import mock

        modulo = self._cargar_adaptador()
        respuesta_ok = mock.MagicMock()
        respuesta_ok.__enter__ = mock.MagicMock(return_value=respuesta_ok)
        respuesta_ok.__exit__ = mock.MagicMock(return_value=False)
        respuesta_ok.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "hola"}}]}).encode()

        error_429 = urllib_error_http(429)
        with mock.patch.object(modulo.urllib.request, "urlopen",
                               side_effect=[error_429, respuesta_ok]) as abrir, \
             mock.patch.object(modulo.time, "sleep"):
            resultado = modulo._llamar("sys", "user", "clave")
        self.assertEqual(resultado, "hola")
        self.assertEqual(abrir.call_count, 2, "debió reintentar tras el 429")

    def test_un_401_no_se_reintenta_porque_es_credencial(self):
        """Reintentar una credencial inválida solo alarga el fallo."""
        from unittest import mock

        modulo = self._cargar_adaptador()
        with mock.patch.object(modulo.urllib.request, "urlopen",
                               side_effect=urllib_error_http(401)) as abrir, \
             mock.patch.object(modulo.time, "sleep"):
            with self.assertRaises(modulo.CredencialInvalidaError):
                modulo._llamar("sys", "user", "clave")
        self.assertEqual(abrir.call_count, 1, "un 401 no debe reintentarse")


class TestModoStreamingDelAdaptador(unittest.TestCase):
    """`TUKUL_EVAL_STREAM` mide modelos que solo responden bien en streaming.

    `Qwen/Qwen3.5-9B` (DeepInfra) devuelve vacío o corta la conexión en
    no-streaming; en streaming responde. Sin este modo, el eval lo mediría con
    salida vacía y TODOS los casos fallarían por el modelo, no por el contrato.
    En modo streaming el adaptador debe reusar el `LLMClient` real del repo, que
    ya habla SSE, en vez de reimplementar el parseo.
    """

    def _cargar_adaptador(self):
        import importlib.util

        adaptador = RAIZ / "evals" / "proveedor_tukul.py"
        spec = importlib.util.spec_from_file_location("proveedor_tukul_stream_test", adaptador)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_modo_streaming_activo_segun_entorno(self):
        import os
        from unittest import mock

        modulo = self._cargar_adaptador()
        for valor, esperado in (("1", True), ("true", True), ("0", False), ("", False), ("no", False)):
            with mock.patch.dict(os.environ, {"TUKUL_EVAL_STREAM": valor}, clear=False):
                # La lectura es dinámica: se consulta el entorno en cada llamada.
                self.assertEqual(modulo._usar_streaming(), esperado,
                                 f"TUKUL_EVAL_STREAM={valor!r}")

    def test_en_modo_streaming_se_usa_el_llmclient_del_repo(self):
        """El eval debe medir el transporte real (SSE), no uno paralelo."""
        import os
        from unittest import mock

        modulo = self._cargar_adaptador()
        chunk = mock.MagicMock(content="Hola", input_tokens=None, output_tokens=None)
        cliente = mock.MagicMock()
        cliente.stream.return_value = iter([chunk])
        with mock.patch.dict(os.environ, {"TUKUL_EVAL_STREAM": "1"}), \
             mock.patch.object(modulo, "LLMClient", return_value=cliente):
            salida = modulo._llamar("sys", "user", "clave")
        self.assertEqual(salida, "Hola")
        self.assertTrue(cliente.stream.called, "debe usar LLMClient.stream en modo streaming")

    def test_los_429_agotan_el_presupuesto_y_degradan_a_error(self):
        """Si el proveedor sigue ocupado, el error llega con un motivo claro."""
        from unittest import mock

        modulo = self._cargar_adaptador()
        with mock.patch.object(modulo.urllib.request, "urlopen",
                               side_effect=urllib_error_http(429)) as abrir, \
             mock.patch.object(modulo.time, "sleep"):
            with self.assertRaises(modulo.ProveedorOcupadoError):
                modulo._llamar("sys", "user", "clave")
        self.assertEqual(abrir.call_count, modulo.MAX_INTENTOS)


def urllib_error_http(code: int):
    """Construye un `HTTPError` con el cuerpo que devuelve DeepInfra."""
    import io
    import urllib.error

    cuerpo = json.dumps({"error": {"message": "Model busy, retry later"}}).encode()
    return urllib.error.HTTPError(
        "https://api.deepinfra.com/v1/openai/chat/completions", code, "busy",
        {}, io.BytesIO(cuerpo),
    )
