"""Contrato C1: la firma keyless existe, es obligatoria y es verificable.

Prueba sobre el YAML real del workflow —no sobre una copia en el documento— tres
propiedades que, si se pierden, dejan el release «firmado» solo de nombre:

1. El job `release` concede `id-token: write` (sin OIDC de GitHub no hay
   certificado y la firma keyless es imposible).
2. La firma NO es tolerante a fallos (sin `|| true`, sin `continue-on-error`).
3. El comando de verificación que documenta `docs/RELEASE.md` es el mismo que
   ejecuta el CI, para que el usuario no verifique con una identidad distinta.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOW = RAIZ / ".github" / "workflows" / "build-release.yml"
RELEASE_DOC = RAIZ / "docs" / "RELEASE.md"


def _pasos(nombre: str) -> list[dict]:
    datos = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for paso in datos["jobs"][nombre]["steps"]:
        if paso.get("name") == nombre or paso.get("name", "").startswith(nombre):
            return [paso]
    raise AssertionError(f"No existe el paso «{nombre}» en el workflow")


class TestFirmaObligatoria(unittest.TestCase):
    def setUp(self):
        self.datos = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.release = self.datos["jobs"]["release"]

    def test_el_job_de_release_pide_el_token_oidc(self):
        permisos = self.release.get("permissions", {})
        self.assertEqual(
            permisos.get("id-token"), "write",
            "Sin `id-token: write` cosign no puede obtener el certificado "
            "efímero de Fulcio y la firma keyless falla en el primer tag.",
        )

    def test_la_firma_se_ejecuta_antes_de_publicar_el_release(self):
        nombres = [paso.get("name", "") for paso in self.release["steps"]]
        firmar = next(i for i, n in enumerate(nombres) if "Sign" in n)
        verificar = next(i for i, n in enumerate(nombres) if "Verify" in n)
        publicar = next(i for i, n in enumerate(nombres) if "Publish" in n)
        self.assertLess(firmar, verificar)
        self.assertLess(verificar, publicar)

    def test_ningun_paso_de_firma_tolera_fallos(self):
        for paso in self.release["steps"]:
            nombre = paso.get("name", "")
            if "Sign" not in nombre and "Verify" not in nombre:
                continue
            self.assertNotEqual(
                paso.get("continue-on-error"), True,
                f"«{nombre}» no puede tolerar fallos: un release sin firma "
                "valida es peor que ninguno.",
            )
            guion = paso.get("run", "")
            self.assertNotIn(
                "|| true", guion,
                f"«{nombre}» silencia el error, y con él la garantía de firma.",
            )

    def test_cosign_esta_fijado_por_sha(self):
        instaladores = [
            paso for paso in self.release["steps"]
            if "cosign-installer" in str(paso.get("uses", ""))
        ]
        self.assertTrue(instaladores, "Falta el paso de instalación de cosign.")
        uses = instaladores[0]["uses"]
        sha = uses.split("@", 1)[1].split()[0]
        self.assertRegex(
            sha, r"^[0-9a-f]{40}$",
            "La acción debe estar fijada por SHA completo, como el resto del "
            "workflow; un tag flotante es una cadena de suministro sin control.",
        )

    def test_no_usa_las_flags_eliminadas_de_cosign_3x(self):
        """cosign 3.x quitó `--output-signature`/`--output-certificate`.

        Estaban en la primera versión de este workflow y habrían fallado en el
        primer tag; el bundle es la única salida verificable.
        """
        for paso in self.release["steps"]:
            guion = paso.get("run", "")
            self.assertNotIn("--output-signature", guion)
            self.assertNotIn("--output-certificate", guion)
            if "sign-blob" in guion:
                self.assertIn("--bundle", guion)


class TestDocumentoYScriptCoinciden(unittest.TestCase):
    """El usuario verifica con el comando del documento; debe ser el del CI."""

    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.documento = RELEASE_DOC.read_text(encoding="utf-8")
        self.script = (RAIZ / "scripts" / "verify-signature.sh").read_text(encoding="utf-8")

    def _regex_identidad(self, texto: str) -> str:
        coincidencia = re.search(
            r"certificate-identity-regexp[\"']?\s+(?:\"|')?(\^https://[^\"''\n]+)", texto
        )
        self.assertIsNotNone(coincidencia, "No hay regex de identidad verificable.")
        return coincidencia.group(1).rstrip("\\")

    def test_documentado_trabajo_script_verifican_la_misma_identidad(self):
        del_workflow = self._regex_identidad(self.workflow)
        # En el documento el repo va literal; el workflow y el script lo
        # interpolan, así que parte de su variable `REPO` (que vale el repo).
        con_repo = del_workflow.replace("${REPO}", "${REPO}")
        literal = del_workflow.replace("${REPO}", "IA-Alex/tukul")
        self.assertIn(literal, self.documento)
        self.assertIn(con_repo, self.script)

    def test_todos_exigen_el_emisor_oidc_de_github(self):
        emisor = "https://token.actions.githubusercontent.com"
        for texto in (self.workflow, self.documento, self.script):
            self.assertIn(emisor, texto)


if __name__ == "__main__":
    unittest.main()
