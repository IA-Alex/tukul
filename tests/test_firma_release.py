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


class TestGlobDeFirma(unittest.TestCase):
    """Regresión de v0.6.0 (run 43480365838).

    El bucle de firma usaba `dist/tukul-*`, que incluye el `.bundle` en cuanto
    existe. En el job `release` el bundle lo crea el paso anterior, así que la
    verificación intentó `...bundle.bundle` y el Release no se publicó —el
    comportamiento correcto, pero por un glob equivocado—. El patrón debe
    seleccionar el binario y NO su bundle.
    """

    def setUp(self):
        self.datos = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    @staticmethod
    def _coincide(patron: str) -> list[str]:
        """Expande el patrón en un directorio temporal, igual que bash en CI."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directorio:
            for nombre in ("tukul-linux-x86_64", "tukul-linux-x86_64.bundle"):
                (Path(directorio) / nombre).touch()
            salida = subprocess.run(
                ["bash", "-c", f'for f in {patron}; do echo "$f"; done'],
                capture_output=True, text=True, check=True, cwd=directorio,
            ).stdout
        return salida.split()

    def test_el_patron_de_firma_excluye_el_bundle(self):
        for job in ("release", "firma-ensayo"):
            for paso in self.datos["jobs"][job]["steps"]:
                guion = paso.get("run", "")
                if "sign-blob" not in guion and "verify-blob" not in guion:
                    continue
                # El archivo firmado: el último argumento que apunta a `dist/`.
                # El primero puede ser el `--bundle` de salida, que no se firma.
                candidatos = [
                    palabra.rstrip(";").split("/")[-1]
                    for palabra in guion.split()
                    if palabra.rstrip(";").startswith("dist/tukul-")
                ]
                self.assertTrue(
                    candidatos, f"{job}/{paso['name']}: sin archivo a firmar."
                )
                patron = candidatos[-1]
                elegidos = self._coincide(patron)
                self.assertEqual(
                    elegidos, ["tukul-linux-x86_64"],
                    f"{job}/{paso['name']}: el patrón «{patron}» firmaría el bundle.",
                )


class TestEnsayoConOidcReal(unittest.TestCase):
    """El ensayo permite probar la firma con OIDC real sin publicar Release."""

    def setUp(self):
        self.datos = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.ensayo = self.datos["jobs"]["firma-ensayo"]

    def test_solo_corre_en_disparo_manual(self):
        self.assertEqual(self.ensayo["if"], "github.event_name == 'workflow_dispatch'")

    def test_pide_oidc_y_no_permiso_de_escritura(self):
        permisos = self.ensayo["permissions"]
        self.assertEqual(permisos.get("id-token"), "write")
        self.assertEqual(
            permisos.get("contents"), "read",
            "El ensayo no debe poder publicar un Release: sin `contents: write` "
            "no hay forma de crear ni modificar uno.",
        )

    def test_firma_y_verifica_sin_publicar(self):
        pasos = self.ensayo["steps"]
        guiones = " ".join(paso.get("run", "") for paso in pasos)
        self.assertIn("sign-blob", guiones)
        self.assertIn("verify-blob", guiones)
        nombres = " ".join(str(paso) for paso in pasos).lower()
        self.assertNotIn("action-gh-release", nombres)


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
        # Solo el job `release`: el ensayo usa otra ref (`refs/heads/...`),
        # por diseño, para que no pueda confundirse con un tag firmado.
        datos = yaml.safe_load(self.workflow)
        del_release = "\n".join(
            paso.get("run", "") for paso in datos["jobs"]["release"]["steps"]
        )
        del_workflow = self._regex_identidad(del_release)
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
