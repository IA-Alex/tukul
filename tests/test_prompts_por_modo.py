"""Regresión de F5/F6: prompt de sistema por modo, con defensa común.

Contrato de referencia: `docs/contracts/contratos-0.8.md`.

**Qué fallaba antes (comprobado sobre `0.7.2`).** Había un único
`SYSTEM_PROMPT` para las tres tareas. El contrato de revisión ocupaba la
mayoría del texto, así que:

- en modo conversación el modelo recibía la orden de devolver el contrato JSON
  de revisión y respondía describiendo su propio rol de guardián;
- el enriquecimiento de ideas recibía un contrato JSON que no le aplica.

**Cómo se prueba en ambas direcciones.** Las aserciones de separación fallan
con el prompt único (las tres constantes serían el mismo literal) y pasan con
los tres prompts por modo. Las de defensa fallan si alguien añade un modo sin
la base común.
"""

from __future__ import annotations

import json
import unittest

from tukul_core.llm import SYSTEM_PROMPT
from tukul_core.prompts import (
    BASE_SEGURIDAD,
    CONVERSACION,
    ENRIQUECIMIENTO,
    MODO_POR_DEFECTO,
    PROMPTS,
    REVISION,
    modos_disponibles,
    prompt_sistema,
)

#: Fragmento que solo tiene sentido en el contrato de revisión.
MarcaRe = "contrato JSON de la revisión"
#: Señales de la defensa que NINGÚN modo puede perder.
DEFENSAS = (
    "datos no confiables",
    "redefinan tu rol",
    "nunca reveles",
    "no cambies de rol",
    # Endurecimiento 2026-11-25: el resultado de una herramienta o consulta
    # externa también es dato, no instrucción. Si se pierde, una respuesta de
    # un servidor MCP o un resumen de fuentes podría redefinir el rol.
    "resultado de una herramienta",
)


class TestSeparacionPorModo(unittest.TestCase):
    """F5: cada modo recibe el prompt de su tarea, no el de otra."""

    def test_hay_tres_modos_distintos(self):
        self.assertEqual(modos_disponibles(), ("conversacion", "revision", "enriquecimiento"))
        textos = {prompt_sistema(m) for m in modos_disponibles()}
        self.assertEqual(len(textos), 3, "Los tres modos deben enviar textos distintos")

    def test_conversacion_no_envia_el_contrato_de_revision(self):
        """Regresión del síntoma: el chat respondía con el rol de guardián.

        Con el prompt único, `prompt_sistema("conversacion")` contenía la marca
        del contrato de revisión; el modelo la obedecía en una conversación.
        """
        self.assertNotIn(MarcaRe, prompt_sistema("conversacion"))
        self.assertNotIn(MarcaRe, CONVERSACION)

    def test_enriquecimiento_no_envia_el_contrato_de_revision(self):
        self.assertNotIn(MarcaRe, prompt_sistema("enriquecimiento"))

    def test_revision_conserva_el_contrato_completo(self):
        """El contrato de revisión no puede degradarse al separarlo.

        Los evals miden esta conducta; si el texto pierde alguna de estas
        piezas, `parse_findings` deja de distinguir «sin errores» de «obedecí
        una petición de omitir».
        """
        texto = prompt_sistema("revision")
        self.assertIn(MarcaRe, texto)
        self.assertIn("Reporta SIEMPRE", texto)
        self.assertIn("omitted", texto)
        self.assertNotIn("devuelvas una revisión vacía en silencio\".", texto)

    def test_conversacion_pide_hablar_del_articulo(self):
        texto = prompt_sistema("conversacion")
        self.assertIn("autor", texto)
        self.assertIn("prosa", texto)


class TestDefensaComun(unittest.TestCase):
    """F6: ningún modo queda sin la base de seguridad."""

    def test_cada_modo_conserva_la_base_de_seguridad(self):
        for modo in modos_disponibles():
            texto = prompt_sistema(modo)
            with self.subTest(modo=modo):
                self.assertIn(BASE_SEGURIDAD, texto,
                              f"El modo {modo} perdió la base común de defensa")
                for senal in DEFENSAS:
                    self.assertIn(senal.lower(), texto.lower(),
                                  f"El modo {modo} perdió la defensa «{senal}»")

    def test_los_prompts_de_modo_no_duplican_la_base(self):
        """Duplicar la defensa dejaría modos desincronizados en el próximo cambio."""
        for modo, propio in PROMPTS.items():
            with self.subTest(modo=modo):
                self.assertNotIn(BASE_SEGURIDAD, propio,
                                 f"{modo} repite la base: un endurecimiento futuro "
                                 "se aplicaría solo a algunos modos")


class TestCompatibilidadYSeleccion(unittest.TestCase):
    """El nombre histórico y los llamadores sin modo no cambian de conducta."""

    def test_system_prompt_sigue_siendo_el_de_revision(self):
        self.assertEqual(SYSTEM_PROMPT, prompt_sistema("revision"))

    def test_sin_modo_se_usa_el_por_defecto(self):
        self.assertEqual(MODO_POR_DEFECTO, "revision")
        self.assertEqual(prompt_sistema(None), prompt_sistema("revision"))

    def test_un_modo_desconocido_cae_al_defecto_sin_perder_defensa(self):
        """Un perfil personalizado no debe romper la petición ni saltarse la defensa."""
        texto = prompt_sistema("modo-inventado")
        self.assertIn(BASE_SEGURIDAD, texto)


class TestElClienteEnviaElModo(unittest.TestCase):
    """El modo llega al cuerpo HTTP, no solo a la constante."""

    def _cuerpo(self, modo: str) -> dict:
        from tukul_core.llm import LLMClient
        from tukul_core.models import LlmProfile

        perfil = LlmProfile(
            model="m", endpoint="https://api.example.invalid/v1/chat/completions",
            api_key_env="X", provider="openai_chat_completions",
        )
        request = LLMClient()._request(perfil, "k", "prompt", stream=False, modo=modo)
        return json.loads(request.data)

    def test_el_system_del_payload_corresponde_al_modo(self):
        for modo in modos_disponibles():
            with self.subTest(modo=modo):
                cuerpo = self._cuerpo(modo)
                sistema = cuerpo["messages"][0]
                self.assertEqual(sistema["role"], "system")
                self.assertEqual(sistema["content"], prompt_sistema(modo))

    def test_sin_modo_el_cuerpo_lleva_el_de_revision(self):
        self.assertEqual(self._cuerpo(None)["messages"][0]["content"],
                         prompt_sistema("revision"))


if __name__ == "__main__":
    unittest.main()
