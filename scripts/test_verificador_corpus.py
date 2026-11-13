#!/usr/bin/env python3
"""Prueba negativa del verificador: comprueba que FALLA cuando debe.

Copia `Articulos/_eval/` a un directorio temporal, introduce un defecto
conocido en cada copia y exige que `verificar_corpus_eval.py` lo detecte.
No toca el corpus real.

Uso: python scripts/test_verificador_corpus.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "Articulos" / "_eval"
VERIFICADOR = RAIZ / "scripts" / "verificar_corpus_eval.py"


def ejecutar(raiz: Path) -> dict[str, object]:
    """Ejecuta el verificador sobre una raíz temporal y devuelve el JSON."""
    script = raiz / "scripts" / "verificar_corpus_eval.py"
    salida = subprocess.run(
        [sys.executable, str(script), "--json"],
        capture_output=True, text=True, check=False,
    )
    try:
        datos: dict[str, object] = json.loads(salida.stdout)
        return datos
    except json.JSONDecodeError:
        return {"resultados": [], "fallidas": ["<sin JSON>"], "stderr": salida.stderr}


def fallos(resultado: dict[str, object]) -> dict[str, set[str]]:
    resultados = resultado.get("resultados")
    if not isinstance(resultados, list):
        return {}
    fallos_por_art: dict[str, set[str]] = {}
    for res in resultados:
        if isinstance(res, dict) and not res.get("ok"):
            checks = res.get("checks") or []
            fallos_por_art[str(res.get("id"))] = {
                str(c.get("nombre")) for c in checks
                if isinstance(c, dict) and not c.get("ok")
            }
    return fallos_por_art


CASOS: list[tuple[str, str, Callable[[Path], None]]] = []


def caso(nombre: str, archivo: str, mutacion: Callable[[Path], None], nombre_check: str) -> None:
    CASOS.append((nombre, f"{archivo}|{nombre_check}", mutacion))


def _editar(archivo: str, fn):
    def mutar(corpus: Path) -> None:
        p = corpus / archivo
        p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8")
    return mutar


caso("A-02 con una cifra", "A-02.md", _editar("A-02.md", lambda t: t + "\n\nHay 7 edificios.\n"), "sin cifras (control F-01)")
caso("A-01 sin nombres propios", "A-01.md", _editar("A-01.md", lambda t: t.replace("Fraunhofer", "un instituto").replace("Zúrich", "una ciudad").replace("Escuela Politécnica", "una escuela").replace("Agencia Internacional de la Energía", "un organismo internacional")), "nombres propios ≥ mínimo")
caso("A-06 con muletilla", "A-06.md", _editar("A-06.md", lambda t: t.replace("El agua llega", "O sea, el agua llega", 1)), "A-06 sin muletillas")
caso("A-08 con dos párrafos", "A-08.md", _editar("A-08.md", lambda t: t.replace("Ninguna de esas señales", "\n\nNinguna de esas señales", 1)), "párrafos de texto")
caso("A-10 sin muletillas", "A-10.md", _editar("A-10.md", lambda t: t.replace("En plan", "Por ejemplo").replace("O sea", "Es decir").replace("Pues bien", "Ahora").replace("Pues nada", "Bien").replace("Vale, sí", "Sí")), "muletillas ≥ mínimo")
caso("A-07 con offset movido", "A-07.errores.yaml", _editar("A-07.errores.yaml", lambda t: t.replace("[353, 359]", "[354, 360]")), "A07-E1: offset correcto")
def _quitar_tercer_error(t: str) -> str:
    """Elimina el bloque del tercer error del bloque yaml, dejando 2 errores."""
    ini = t.index("  - id: A07-E3")
    fin = t.index("```", ini)
    return t[:ini] + t[fin:]


caso("A-07 con 2 errores", "A-07.errores.yaml", _editar("A-07.errores.yaml", _quitar_tercer_error), "exactamente 3 errores")
caso("A-05 con título corto", "A-05.md", _editar("A-05.md", lambda t: "# Documentar decisiones\n" + t.split("\n", 1)[1]), "título largo")
caso("A-04 editado (debe romper la copia)", "A-04.md", _editar("A-04.md", lambda t: t.replace("Leí primero", "Leí antes", 1)), "A-04 idéntico byte a byte al original")
caso("artículo ausente", "A-03.md", lambda corpus: (corpus / "A-03.md").unlink(), "existe")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="test-verificador-"))
    fallidas: list[str] = []
    try:
        for nombre, objetivo, mutar, check in [
            (n, o.split("|")[0], m, o.split("|")[1]) for n, o, m in CASOS
        ]:
            raiz = base / nombre.replace(" ", "_")
            shutil.copytree(RAIZ / "Articulos", raiz / "Articulos")
            shutil.copytree(RAIZ / "scripts", raiz / "scripts",
                            ignore=shutil.ignore_patterns("__pycache__"))
            mutar(raiz / "Articulos" / "_eval")
            detectados = fallos(ejecutar(raiz))
            ok = check in detectados.get(objetivo.split(".")[0], set())
            print(f"{'ok  ' if ok else 'FALLA'} {nombre:<40} → se esperaba fallo en {objetivo}:{check!r}")
            if not ok:
                fallidas.append(f"{nombre} (detectado: {detectados})")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    if fallidas:
        print(f"PRUEBA NEGATIVA FALLIDA en {len(fallidas)} caso(s):")
        for f in fallidas:
            print("  -", f)
        return 1
    print(f"PRUEBA NEGATIVA OK: {len(CASOS)}/{len(CASOS)} defectos detectados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
