"""Motivos de omisión declarados por el modelo: normalización del formato.

El defecto que fija esta suite se observó contra DeepInfra al añadir el campo
opcional `omitted` (ver `SYSTEM_PROMPT` y `review.omitted_reasons`). Sin un
ejemplo literal en el prompt, el modelo metió la representación de un objeto
dentro de la cadena:

    {"findings": [], "omitted": ["{'original': 'introdución', 'reason': '…'}"]}

El formato no es fiable porque el modelo es un generador no determinista: la
aplicación no puede depender de su obediencia para el formato. `omitted_reasons`
normaliza cada forma observada (cadena simple, objeto JSON, `repr` de dict de
Python) y descarta lo que no da texto legible, en vez de mostrar un `repr` roto
al usuario.

Estas pruebas no llaman a ningún proveedor: fijan la normalización con las
formas reales y las basura plausibles.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_core.review import diagnose_findings, omitted_reasons, parse_findings


def _respuesta(omitted: object, *, findings: list | None = None) -> str:
    """Serializa una respuesta del modelo con el campo `omitted` dado."""
    payload: dict[str, object] = {"findings": findings if findings is not None else []}
    payload["omitted"] = omitted
    return json.dumps(payload, ensure_ascii=False)


class TestOmisionesDeclaradas(unittest.TestCase):
    """`omitted_reasons` devuelve siempre una lista de motivos legibles."""

    def test_cadena_simple_se_conserva(self):
        self.assertEqual(
            omitted_reasons(_respuesta(["petición del usuario"])),
            ["petición del usuario"],
        )

    def test_repr_de_dict_produce_solo_el_motivo(self):
        """El caso real: el modelo mandó el `repr` de un dict dentro de la cadena."""
        crudo = "{'original': 'introdución', 'reason': 'El usuario solicitó omitirlo'}"
        self.assertEqual(
            omitted_reasons(_respuesta([crudo])),
            ["El usuario solicitó omitirlo"],
        )

    def test_objeto_json_produce_solo_el_motivo(self):
        self.assertEqual(
            omitted_reasons(_respuesta([{"reason": "petición del usuario"}])),
            ["petición del usuario"],
        )

    def test_acepta_la_clave_motivo(self):
        self.assertEqual(
            omitted_reasons(_respuesta([{"motivo": "petición del usuario"}])),
            ["petición del usuario"],
        )

    def test_varias_formas_en_la_misma_lista(self):
        respuesta = _respuesta([
            "simple",
            {"reason": "objeto"},
            "{'reason': 'repr'}",
        ])
        self.assertEqual(omitted_reasons(respuesta), ["simple", "objeto", "repr"])

    def test_descarta_lo_que_no_da_texto_legible(self):
        for basura in (
            [123, None, True],
            [{"foo": "bar"}],
            [{"reason": {"anidado": 1}}],
            [{"suggestion": "x", "reason": ""}],
            ["{'reason': malformado"],
        ):
            with self.subTest(basura=basura):
                self.assertEqual(omitted_reasons(_respuesta(basura)), [])

    def test_sin_campo_omitted_no_cambia_nada(self):
        """Retrocompatibilidad: las respuestas previas al cambio siguen igual."""
        sin_campo = json.dumps({"findings": []})
        self.assertEqual(omitted_reasons(sin_campo), [])
        self.assertEqual(parse_findings(sin_campo), [])

    def test_no_lista_o_json_invalido_devuelve_vacio(self):
        for entrada in ("", "texto en prosa", _respuesta("no soy una lista")):
            with self.subTest(entrada=entrada):
                self.assertEqual(omitted_reasons(entrada), [])

    def test_parse_findings_ignora_el_campo_omitted(self):
        """El hallazgo declarado no debe colarse como hallazgo de la revisión."""
        respuesta = _respuesta(
            ["petición del usuario"],
            findings=[{
                "category": "ortografía", "severity": "alta",
                "original": "introdución", "suggestion": "introducción",
                "reason": "falta una letra",
            }],
        )
        self.assertEqual(len(parse_findings(respuesta)), 1)
        causa, hallazgos = diagnose_findings(respuesta)
        self.assertEqual(causa, "ok")
        self.assertEqual(len(hallazgos), 1)


if __name__ == "__main__":
    unittest.main()
