"""El corpus de evaluación y su verificador, dentro de la puerta de calidad.

Motivo: `scripts/verificar_corpus_eval.py` y `scripts/test_verificador_corpus.py`
vivían fuera de la suite. Si alguien editaba un artículo del corpus o el propio
verificador, nada lo detectaba hasta que la batería daba resultados falsos.

Estas pruebas conectan ambos: el verificador debe pasar sobre el corpus real y
debe fallar ante un corpus manipulado. La prueba negativa es la que garantiza
que el verificador no se limita a aprobarlo todo.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "Articulos" / "_eval"
VERIFICADOR = RAIZ / "scripts" / "verificar_corpus_eval.py"
PRUEBA_NEGATIVA = RAIZ / "scripts" / "test_verificador_corpus.py"
ARTICULOS = [f"A-{n:02d}" for n in range(1, 11)]


def ejecutar(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, check=False, cwd=RAIZ,
    )


class TestCorpusPresente(unittest.TestCase):
    def test_los_diez_articulos_existen(self):
        faltan = [a for a in ARTICULOS if not (CORPUS / f"{a}.md").is_file()]
        self.assertEqual(faltan, [], f"Faltan artículos del corpus: {faltan}")

    def test_el_registro_de_errores_acompana_a_a07(self):
        registro = CORPUS / "A-07.errores.yaml"
        self.assertTrue(registro.is_file(), "A-07 necesita su registro de errores.")
        texto = registro.read_text(encoding="utf-8")
        self.assertEqual(texto.count("id: A07-E"), 3)

    def test_el_corpus_no_contiene_secretos(self):
        for articulo in CORPUS.glob("*.md"):
            contenido = articulo.read_text(encoding="utf-8").lower()
            for marca in ("api_key", "sk-", "deepinfra_api_key"):
                self.assertNotIn(marca, contenido, f"{articulo.name} menciona {marca}")


class TestVerificadorSobreElCorpusReal(unittest.TestCase):
    def test_el_verificador_aprueba_el_corpus(self):
        resultado = ejecutar(VERIFICADOR)
        self.assertEqual(
            resultado.returncode, 0,
            f"El corpus no pasa su propio verificador:\n{resultado.stdout[-2000:]}",
        )

    def test_estricto_falla_mientras_queden_revisiones_humanas(self):
        """A-06 y A-07 exigen juicio humano; --estricto no debe dar verde."""
        resultado = ejecutar(VERIFICADOR, "--estricto")
        self.assertEqual(
            resultado.returncode, 1,
            "Con revisiones humanas pendientes, --estricto debe salir en rojo.",
        )

    def test_el_json_declara_los_pendientes_humanos(self):
        resultado = ejecutar(VERIFICADOR, "--json")
        datos = json.loads(resultado.stdout)
        self.assertEqual(sorted(datos["pendientes_humanos"]), ["A-06", "A-07"])
        self.assertEqual(datos["codigo"], 0)


class TestVerificadorDetectaManipulacion(unittest.TestCase):
    """Un corpus alterado no puede seguir pasando: si pasa, el verificador miente."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        shutil.copytree(CORPUS, self.raiz / "Articulos" / "_eval")
        (self.raiz / "scripts").mkdir()
        shutil.copy(VERIFICADOR, self.raiz / "scripts")

    def tearDown(self):
        self.directorio.cleanup()

    def _verificar(self) -> subprocess.CompletedProcess[str]:
        return ejecutar(self.raiz / "scripts" / "verificar_corpus_eval.py")

    def test_una_cifra_en_el_control_negativo_rompe_la_verificacion(self):
        a02 = self.raiz / "Articulos" / "_eval" / "A-02.md"
        a02.write_text(a02.read_text(encoding="utf-8") + "\nHay 3 casos.\n", encoding="utf-8")
        resultado = self._verificar()
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("sin cifras", resultado.stdout)

    def test_quitar_un_articulo_rompe_la_verificacion(self):
        (self.raiz / "Articulos" / "_eval" / "A-05.md").unlink()
        resultado = self._verificar()
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("A-05", resultado.stdout)

    def test_mover_un_offset_del_registro_rompe_la_verificacion(self):
        registro = self.raiz / "Articulos" / "_eval" / "A-07.errores.yaml"
        registro.write_text(
            registro.read_text(encoding="utf-8").replace("offset: [353, 359]", "offset: [354, 359]"),
            encoding="utf-8",
        )
        resultado = self._verificar()
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("offset", resultado.stdout)


class TestPruebaNegativaDelProyecto(unittest.TestCase):
    """La batería de defectos que acompaña al verificador sigue detectando."""

    def test_la_prueba_negativa_detecta_todos_los_defectos(self):
        resultado = ejecutar(PRUEBA_NEGATIVA)
        self.assertEqual(
            resultado.returncode, 0,
            f"La prueba negativa falla:\n{resultado.stdout[-1500:]}",
        )
        self.assertIn("10/10", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
