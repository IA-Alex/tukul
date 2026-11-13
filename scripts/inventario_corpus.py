"""Inventario del corpus real de /Articulos frente a los requisitos de la batería.

No evalúa al modelo: mide si el corpus disponible permite ejecutar D1/D2/D3 tal
como están definidas en `docs/BATERIA_EVALUACION_MODELO.md`.

Uso: python scripts/inventario_corpus.py
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "Articulos"
EXTENSIONES = {".md", ".txt"}

# Umbrales de la batería (sección 5): 500–1500 palabras, español, prosa.
MIN_PALABRAS = 500
MAX_PALABRAS = 1500

_FALTAS_TIPICAS = re.compile(
    r"\b(haber|hacer|venir)\s+(?:a|para)\s+(?:ver|hacer)\b|\bhabían\b|\bhaiga\b|\bdijieron\b",
    re.IGNORECASE,
)
_MULETILLAS = re.compile(r"\b(o sea|en plan|pues|es que|bueno,\s)\b", re.IGNORECASE)
_CIFRAS = re.compile(r"\b\d[\d.,]*\b")
_FECHAS = re.compile(r"\b(?:19|20)\d{2}\b")
_NOMBRES = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b")


def _idioma_es(texto: str) -> float:
    """Heurística simple: proporción de palabras funcionales españolas."""
    comunes = {
        "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las",
        "un", "por", "con", "una", "su", "para", "es", "al", "como", "más",
    }
    palabras = re.findall(r"[a-záéíóúñ]+", texto.lower())
    if not palabras:
        return 0.0
    return sum(1 for p in palabras if p in comunes) / len(palabras)


def analizar(ruta: Path) -> dict:
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    palabras = len(texto.split())
    parrafos = [p for p in re.split(r"\n\s*\n", texto) if p.strip()]
    return {
        "ruta": str(ruta.relative_to(RAIZ)),
        "palabras": palabras,
        "parrafos": len(parrafos),
        "espanol": round(_idioma_es(texto), 2),
        "cifras": len(_CIFRAS.findall(texto)),
        "fechas": len(_FECHAS.findall(texto)),
        "nombres": len(set(_NOMBRES.findall(texto))),
        "faltas": len(_FALTAS_TIPICAS.findall(texto)),
        "muletillas": len(_MULETILLAS.findall(texto)),
        "tiene_h1": bool(re.search(r"^#\s", texto, re.MULTILINE)),
        "en_rango": MIN_PALABRAS <= palabras <= MAX_PALABRAS,
    }


def main() -> None:
    archivos = sorted(
        p for p in RAIZ.rglob("*") if p.suffix.lower() in EXTENSIONES and p.is_file()
    )
    filas = [analizar(p) for p in archivos]
    filas.sort(key=lambda f: -f["palabras"])

    cabecera = f"{'artículo':58} {'pal.':>6} {'párr.':>6} {'es':>4} {'rango':>6} {'faltas':>6} {'mulet.':>6}"
    print(cabecera)
    print("-" * len(cabecera))
    for f in filas:
        print(
            f"{f['ruta'][:58]:58} {f['palabras']:>6} {f['parrafos']:>6} "
            f"{f['espanol']:>4} {'SÍ' if f['en_rango'] else 'no':>6} "
            f"{f['faltas']:>6} {f['muletillas']:>6}"
        )

    validos = [f for f in filas if f["en_rango"] and f["espanol"] >= 0.15]
    print("\n" + "=" * 70)
    print(f"archivos de prosa: {len(filas)}")
    print(f"válidos para D1 (500-1500 palabras, español): {len(validos)}  (requisito: 10)")
    if validos:
        print(f"  media de palabras: {statistics.mean(f['palabras'] for f in validos):.0f}")
        print(f"  con H1 (títulos para I-09): {sum(1 for f in validos if f['tiene_h1'])}")
        print(f"  con cifras (F-01, I-01): {sum(1 for f in validos if f['cifras'] >= 5)}")
        print(f"  con faltas sembradas reales: {sum(1 for f in validos if f['faltas'])}")
        print(f"  con muletillas (I-10): {sum(1 for f in validos if f['muletillas'])}")
    fuera = [f for f in filas if not f["en_rango"]]
    print(f"\nfuera de rango ({len(fuera)}):")
    for f in fuera:
        motivo = "demasiado corto" if f["palabras"] < MIN_PALABRAS else "demasiado largo"
        print(f"  - {f['ruta'][:56]:56} {f['palabras']:>6} palabras ({motivo})")


if __name__ == "__main__":
    main()
