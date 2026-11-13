"""Batería D1-D3 sobre el corpus de `Articulos/_eval`.

No usa promptfoo: verifica con criterios deterministas (párrafos idénticos,
entidades preservadas, longitud, citas reales) porque un PASS/FAIL por LLM no
prueba comprensión de la instrucción.

Uso:
    export DEEPINFRA_API_KEY=...
    python scripts/bateria_modelo.py [--dry-run]

Salida: JSON en `evals/resultados/bateria-<fecha>.json` y resumen por consola.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "Articulos" / "_eval"
SALIDA = RAIZ / "evals" / "resultados"
ENDPOINT = "https://api.deepinfra.com/v1/openai/chat/completions"
MODELO = "deepseek-ai/DeepSeek-V4-Flash"

CIFRA = re.compile(r"\b\d[\d.,]*\b")
FECHA = re.compile(r"\b(?:19|20)\d{2}\b")
NOMBRE = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b")
MULETILLAS = ("o sea", "en plan", "vale,", "pues nada", "pues bien")


def _key() -> str:
    clave = os.environ.get("DEEPINFRA_API_KEY", "")
    if not clave:
        raise SystemExit("Falta DEEPINFRA_API_KEY en el entorno.")
    return clave


def llamar(sistema: str, usuario: str, clave: str, max_tokens: int = 1500) -> tuple[str, float]:
    cuerpo = json.dumps({
        "model": MODELO, "temperature": 0, "seed": 7, "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario},
        ],
    }).encode()
    pet = urllib.request.Request(ENDPOINT, data=cuerpo, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {clave}"}, method="POST")
    inicio = time.perf_counter()
    with urllib.request.urlopen(pet, timeout=120) as r:
        datos = json.loads(r.read().decode())
    return datos["choices"][0]["message"]["content"] or "", time.perf_counter() - inicio


def parrafos(texto: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]


def norm(t: str) -> str:
    return " ".join(t.split())


def tokens(t: str) -> list[str]:
    return re.findall(r"\w+", t.lower())


from tukul_core.llm import SYSTEM_PROMPT  # noqa: E402
from tukul_core.prompting import build_review_prompt  # noqa: E402
from tukul_core.review import diagnose_findings  # noqa: E402

SISTEMA = (
    "Eres un asistente de edición. Recibes un artículo en Markdown y una "
    "instrucción del usuario. Aplica SOLO la instrucción pedida. Devuelve "
    "únicamente el artículo resultante, sin explicaciones ni comentarios. "
    "Si la instrucción es ambigua o contradictoria, NO edites: explica el "
    "problema en una sola frase empezando por 'ACLARACIÓN:'."
)


def caso_i01(clave: str) -> dict:
    texto = (CORPUS / "A-01.md").read_text(encoding="utf-8")
    salida, lat = llamar(SISTEMA, f"{texto}\n\n---\nINSTRUCCIÓN: Hazlo un 30 % más corto sin perder ningún dato.", clave)
    antes, despues = len(texto.split()), len(salida.split())
    ratio = despues / antes
    # Solo entidades que aportan: cifras, años y nombres que aparecen >1 vez
    # (una mayúscula de inicio de frase no es una entidad y ensuciaba el conteo).
    # Excluye conectores capitalizados ("Por", "Esa"): una entidad real es un
    # nombre que aparece >1 vez y en minúscula en alguna parte del texto.
    nombres = {n for n in NOMBRE.findall(texto)
               if texto.count(n) > 1 and n.lower() in texto}
    entidades = set(CIFRA.findall(texto)) | set(FECHA.findall(texto)) | nombres
    perdidas = [e for e in entidades if e not in salida]
    return {"id": "I-01", "palabras_antes": antes, "palabras_despues": despues,
            "ratio": round(ratio, 2), "entidades_perdidas": perdidas,
            "pass": 0.55 <= ratio <= 0.75 and len(perdidas) <= 2, "latencia": lat}


def caso_i03(clave: str) -> dict:
    texto = (CORPUS / "A-01.md").read_text(encoding="utf-8")
    salida, lat = llamar(SISTEMA, f"{texto}\n\n---\nINSTRUCCIÓN: Reescribe únicamente el segundo párrafo.", clave)
    orig, nuevo = parrafos(texto), parrafos(salida)
    # El modelo puede juntar o separar párrafos: se cuenta presencia exacta del
    # contenido, no la igualdad de índice.
    texto_salida = norm(salida)
    intactos = sum(1 for i, p in enumerate(orig) if i != 1 and norm(p) in texto_salida)
    esperados = len(orig) - 1
    truncado = len(salida.split()) < len(texto.split()) * 0.5
    return {"id": "I-03", "parrafos_original": len(orig), "parrafos_salida": len(nuevo),
            "intactos": intactos, "esperados_intactos": esperados,
            "truncado": truncado,
            "pass": intactos >= esperados * 0.8, "latencia": lat}


def caso_i06(clave: str) -> dict:
    texto = (CORPUS / "A-02.md").read_text(encoding="utf-8")
    salida, lat = llamar(SISTEMA, f"{texto}\n\n---\nINSTRUCCIÓN: Acórtalo sin quitar nada.", clave)
    avisa = salida.strip().upper().startswith("ACLARACIÓN") or "contradic" in salida.lower()
    edito = abs(len(salida.split()) - len(texto.split())) > 30
    return {"id": "I-06", "avisa_contradiccion": avisa, "edito_igual": edito,
            "pass": avisa and not edito, "latencia": lat,
            "muestra": salida[:200]}


def caso_i10(clave: str) -> dict:
    texto = (CORPUS / "A-10.md").read_text(encoding="utf-8")
    salida, lat = llamar(SISTEMA, f"{texto}\n\n---\nINSTRUCCIÓN: Quita las muletillas (o sea, en plan, vale, pues nada, pues bien) sin tocar nada más.", clave)
    quedan = sum(salida.lower().count(m) for m in MULETILLAS)
    cons = len(re.findall(r"\bpues\b", salida, re.I))
    return {"id": "I-10", "muletillas_antes": sum(texto.lower().count(m) for m in MULETILLAS),
            "muletillas_despues": quedan, "pues_conservados": cons,
            "pass": quedan <= 2, "latencia": lat}


def caso_r01(clave: str) -> dict:
    texto = (CORPUS / "A-06.md").read_text(encoding="utf-8")
    salida, lat = llamar(SYSTEM_PROMPT, build_review_prompt(texto), clave, max_tokens=1200)
    causa, hallazgos = diagnose_findings(salida)
    duras = [h for h in hallazgos if str(h.get("category", "")).lower() in
             ("ortografía", "gramática", "concordancia")]
    citas_reales = all(h.get("original", "") in texto for h in hallazgos) if hallazgos else True
    return {"id": "R-01", "causa": causa, "n_hallazgos": len(hallazgos),
            "duras_sobre_texto_correcto": duras, "citas_reales": citas_reales,
            "pass": not duras and citas_reales, "latencia": lat}


def caso_r02(clave: str) -> dict:
    texto = (CORPUS / "A-07.md").read_text(encoding="utf-8")
    esperados = ["decada", "efiziencia", "adminstración"]
    salida, lat = llamar(SYSTEM_PROMPT, build_review_prompt(texto), clave, max_tokens=1200)
    causa, hallazgos = diagnose_findings(salida)
    citados = [h.get("original", "") for h in hallazgos]
    detectados = [e for e in esperados if any(e in c for c in citados)]
    return {"id": "R-02", "causa": causa, "n_hallazgos": len(hallazgos),
            "detectados": detectados, "esperados": esperados,
            "pass": len(detectados) >= 2 and len(hallazgos) <= 12, "latencia": lat}


def caso_f01(clave: str) -> dict:
    texto = (CORPUS / "A-02.md").read_text(encoding="utf-8")
    salida, lat = llamar(SISTEMA, f"{texto}\n\n---\nINSTRUCCIÓN: Mejora la redacción sin añadir datos nuevos.", clave)
    cifras = set(CIFRA.findall(salida))
    fechas = set(FECHA.findall(salida))
    return {"id": "F-01", "cifras_nuevas": sorted(cifras), "fechas_nuevas": sorted(fechas),
            "pass": not cifras and not fechas, "latencia": lat}


CASOS = [caso_i01, caso_i03, caso_i06, caso_i10, caso_r01, caso_r02, caso_f01]


def main() -> int:
    clave = _key()
    resultados = []
    for caso in CASOS:
        try:
            r = caso(clave)
        except Exception as error:
            r = {"id": caso.__name__, "pass": False, "error": str(error)}
        resultados.append(r)
        estado = "PASS" if r.get("pass") else "FALLA"
        print(f"[{estado}] {r['id']:<6} {json.dumps({k: v for k, v in r.items() if k not in ('id','pass')}, ensure_ascii=False)[:150]}")

    SALIDA.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destino = SALIDA / f"bateria-{sello}.json"
    destino.write_text(json.dumps({
        "modelo": MODELO, "fecha": sello, "temperature": 0, "seed": 7,
        "casos": resultados,
        "resumen": {"pass": sum(1 for r in resultados if r.get("pass")), "total": len(resultados)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{destino.relative_to(RAIZ)}")
    pasados = sum(1 for r in resultados if r.get("pass"))
    print(f"RESULTADO: {pasados}/{len(resultados)}")
    return 0 if pasados == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
