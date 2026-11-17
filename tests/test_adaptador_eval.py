"""El adaptador del eval distingue revisión vacía de respuesta fuera del contrato.

Motivo (2026-11-16): el eval base cayó 7/8 porque el modelo respondió
`{"review": "…"}` en lugar de `{"findings": […]}`. `diagnose_findings` clasifica
ambas —la lista vacía y el objeto sin `findings`— como `sin_hallazgos` a
propósito, así que el eval no podía saber si el artículo estaba limpio (PASS) o
si el modelo incumplió el contrato (FAIL del modelo). El adaptador publica
ahora `review_shape` para separarlas.

Estas pruebas no llaman a la red: el adaptador admite entrada por stdin para
probarse en seco, y `_forma_de_revision` se importa directamente.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ADAPTADOR = RAIZ / "evals" / "proveedor_tukul.py"


def _cargar_adaptador():
    especificacion = importlib.util.spec_from_file_location("proveedor_tukul", ADAPTADOR)
    assert especificacion is not None and especificacion.loader is not None
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


adaptador = _cargar_adaptador()


class TestFormaDeRevision(unittest.TestCase):
    def test_un_contrato_con_hallazgos_es_findings(self):
        self.assertEqual(
            adaptador._forma_de_revision(
                '{"findings":[{"category":"ortografía","severity":"alta",'
                '"original":"erro","suggestion":"error","reason":"falta la r"}]}'
            ),
            "findings",
        )

    def test_un_array_raiz_tambien_es_findings(self):
        self.assertEqual(
            adaptador._forma_de_revision(
                '[{"category":"gramática","severity":"baja",'
                '"original":"deben de","suggestion":"deben","reason":"obligación"}]'
            ),
            "findings",
        )

    def test_una_lista_vacia_es_revision_vacia(self):
        """Artículo limpio: el modelo no encontró nada. Esto es un PASS."""
        self.assertEqual(adaptador._forma_de_revision('{"findings":[]}'), "vacia")

    def test_un_objeto_sin_findings_es_otra(self):
        """La respuesta observada el 2026-11-16 no puede pasar por «limpio»."""
        self.assertEqual(
            adaptador._forma_de_revision('{"review": "He encontrado un error…", "omitted": null}'),
            "otra",
        )

    def test_la_prosa_sin_json_es_prosa(self):
        self.assertEqual(adaptador._forma_de_revision("He revisado y está bien."), "prosa")

    def test_revision_vacia_y_respuesta_fuera_de_contrato_no_comparten_forma(self):
        """Regresión: el objeto sin `findings` es `esquema_ajeno`, no «limpio».

        Corrige un diagnóstico previo: en la ejecución del 2026-11-16 el caso
        cayó en `sin_hallazgos` porque el modelo respondió «no he revisado» de
        una forma más plana. Ambas variantes deben quedarse fuera de `vacia`,
        que es la única que un artículo limpio puede producir.
        """
        self.assertEqual(adaptador.diagnose_findings('{"review":"x"}')[0], "esquema_ajeno")
        self.assertEqual(adaptador.diagnose_findings('{"findings":[]}')[0], "sin_hallazgos")
        self.assertEqual(adaptador._forma_de_revision('{"review":"x"}'), "otra")
        self.assertEqual(adaptador._forma_de_revision('{"findings":[]}'), "vacia")


class TestModoDelPrompt(unittest.TestCase):
    """H-4 de 0.8.1: el adaptador resuelve el prompt por modo, no por re-export.

    Antes importaba `SYSTEM_PROMPT` de `tukul_core.llm` (que es siempre el
    prompt de revisión), así que no podía ejercitar los otros modos pese a
    documentar que medía «lo que la aplicación envía de verdad».
    """

    def test_por_defecto_usa_el_modo_de_revision(self):
        self.assertEqual(adaptador.MODO_POR_DEFECTO, "revision")
        self.assertEqual(adaptador.prompt_sistema(None), adaptador.prompt_sistema("revision"))

    def test_el_prompt_por_defecto_lleva_el_contrato_de_revision(self):
        """El re-export histórico (`SYSTEM_PROMPT`) era el de revisión."""
        from tukul_core.llm import SYSTEM_PROMPT

        self.assertEqual(adaptador.prompt_sistema(adaptador.MODO_POR_DEFECTO), SYSTEM_PROMPT)

    def test_los_modos_dan_prompts_distintos(self):
        """Si el adaptador siguiera fijo, no habría forma de medir conversación."""
        self.assertNotEqual(
            adaptador.prompt_sistema("revision"),
            adaptador.prompt_sistema("conversacion"),
        )


class TestAdaptadorEnSeco(unittest.TestCase):
    def test_sin_key_el_adaptador_falla_con_un_motivo_legible(self):
        import json
        import os
        import subprocess
        import sys

        entorno = {k: v for k, v in os.environ.items() if k != "DEEPINFRA_API_KEY"}
        entorno["TUKUL_EVAL_API_KEY_ENV"] = "TUKUL_EVAL_KEY_AUSENTE_DE_PRUEBA"
        resultado = subprocess.run(
            [sys.executable, str(ADAPTADOR)],
            input=json.dumps({"vars": {"article": "Texto."}}),
            capture_output=True, text=True, check=False, env=entorno, cwd=RAIZ,
        )
        self.assertEqual(resultado.returncode, 0)
        salida = json.loads(resultado.stdout)
        self.assertIn("TUKUL_EVAL_KEY_AUSENTE_DE_PRUEBA", salida["error"])
        self.assertEqual(salida["output"], "")

    def test_una_key_revocada_explica_el_401_en_vez_de_propagarlo_crudo(self):
        """Regresión: el eval se vio entero en rojo por un 401 sin diagnóstico.

        El proveedor devolvía `invalid_api_key` y el adaptador lo publicaba como
        `HTTP Error 401: Unauthorized`, indistinguible de un fallo de red o de
        contrato. El mensaje debe decir que la credencial no vale y qué
        variable revisar, sin filtrar la key.
        """
        import urllib.error

        def abrir_fallido(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                "https://x/v1/chat/completions", 401, "Unauthorized", {}, None
            )

        original = adaptador.urllib.request.urlopen
        adaptador.urllib.request.urlopen = abrir_fallido
        try:
            with self.assertRaises(adaptador.CredencialInvalidaError) as capturado:
                adaptador._llamar("sistema", "usuario", "sk-secreto-de-prueba")
        finally:
            adaptador.urllib.request.urlopen = original
        mensaje = str(capturado.exception)
        self.assertIn("401", mensaje)
        self.assertIn(adaptador.VARIABLE_KEY, mensaje)
        self.assertNotIn("sk-secreto-de-prueba", mensaje)
