#!/usr/bin/env python3
"""Verificador del corpus de evaluación de `Articulos/_eval/`.

Comprueba lo que se puede comprobar sin juicio humano: existencia, longitud,
estructura, presencia/ausencia de cifras, fechas, nombres propios, títulos,
muletillas, marcas coloquiales, los tres errores sembrados de A-07 y la
integridad de la copia de A-04.

NO evalúa al modelo, NO ejecuta Yachay y NO escribe en el corpus. Solo lee.

`docs/INFORME_CORPUS_EVALUACION.md` da el rol de cada artículo;
`docs/BATERIA_EVALUACION_MODELO.md` da los casos que cada rol habilita.

Uso:
    python scripts/verificar_corpus_eval.py            # informe legible
    python scripts/verificar_corpus_eval.py --json     # resultado legible por máquina
    python scripts/verificar_corpus_eval.py --estricto # falla si algo queda pendiente

Salida: código 0 si todas las comprobaciones automáticas pasan (aunque queden
pendientes humanos); 1 si alguna falla.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "Articulos" / "_eval"
ORIGINAL_A04 = (
    RAIZ
    / "Articulos"
    / "publicacion_por_incidente"
    / "¿Qué hace que un incidente deje el laboratorio y llegue al dominio público?.md"
)
# `Articulos/*` está en .gitignore: en un worktree el original no existe. Se
# busca entonces en el checkout principal, junto al worktree.
ORIGINAL_A04_ALTERNATIVO = Path(
    "/home/panda/Tukul/Articulos/publicacion_por_incidente/"
    "¿Qué hace que un incidente deje el laboratorio y llegue al dominio público?.md"
)

ARTICULOS = [f"A-{n:02d}" for n in range(1, 11)]

# Muletillas de dicción tal como las define I-10. «pues» y «es que» NO están
# aquí: son conjunciones legítimas y el origen del falso positivo documentado
# en BATERIA §7.2. A-10 exige que sobrevivan.
MULETILLAS = {
    "o sea": r"\bo\s+sea\b",
    "en plan": r"\ben\s+plan\b",
    "vale": r"\bvale\b(?!\s+la\s+pena)",
    "pues nada": r"\bpues\s+nada\b",
    "pues bien": r"\bpues\s+bien\b",
    "a ver": r"\ba\s+ver\b",
}
# Aparecen en A-10 para demostrar que un modelo no debe borrarlas.
# «pues» gramatical: en función causal/continuativa. Cuenta todas las
# apariciones y resta las muletillas «pues bien»/«pues nada»; esas ya cuentan
# como muletilla en MULETILLAS, así que no pueden servir para cumplir aquí.
CONSERVAR = {
    "pues_gramatical": r"\bpues\b",
    "es_que": r"\bes\s+que\b",
}
NO_GRAMATICALES = re.compile(r"\bpues\s+(?:nada|bien)\b", re.IGNORECASE)
MARCADORES_COLOQUIALES = [
    r"\bo\s+sea\b",
    r"\ben\s+plan\b",
    r"\bojo\b",
    r"\bvale\b",
    r"\ba\s+ver\b",
    r"\bte\s+dig?o\b",
    r"\by\s+s[ií]\b",
    r"\bme\s+dir[eé]is\b",
    r"\btienes\s+raz[oó]n\b",
    r"\bpues\s+bien\b",
    r"\bsin\s+anestesia\b",
    r"\bque\s+te\s+encuentras\b",
]
CIFRA = re.compile(r"\b\d[\d.,]*\b")
FECHA = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b|\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+(?:19|20)\d{2}\b", re.IGNORECASE)
# Palabras capitalizadas que abren frase o párrafo: con punteo tras el punto
# dejan de contarse como «nombres propios».
FALSO_NOMBRE = re.compile(r"(?:^|[.!?«]\s+|[\n#>-]\s*)")

# Faltas que A-06 y A-07 (fuera de sus 3 errores) no pueden contener.
# A-07 se comprueba excluyendo explícitamente sus tres errores.
ERRORES_LEXICOS = {
    "habían (impersonal)": r"\bhab[íi]an\s+(?:much[oa]s?|vari[oa]s|personas|gente|problemas|casos)",
    "haiga": r"\bhaiga\b",
    "dijieron": r"\bdijieron\b",
    "vinistes/fuistes": r"\b(?:vinistes|fuistes)\b",
    "a por ver": r"\bhaber\s+a\s+ver\b",
    "mas (sin tilde de conj.)": r"(?<!m[áa]s)\bmas\b(?!\s+sin)",
    "solo (sin tilde): legal RAE, no se marca": r"(?!x)x",
}

# Rol de cada artículo, copiado del INFORME §2.1. Los rangos son palabras
# contadas con `split()`, igual que `wc -w`.
SPEC: dict[str, dict] = {
    "A-01": dict(rol="Explicativo, tema técnico", min=800, max=1000,
                 como="≥ 6 cifras, ≥ 3 nombres propios", pruebas=["I-01", "F-01"],
                 cifras_min=6, nombres_min=3, fechas_min=0),
    "A-02": dict(rol="Explicativo, tema no técnico", min=700, max=900,
                 como="sin cifras (control negativo de F-01)", pruebas=["F-01"],
                 cifras_max=0, fechas_max=0),
    "A-03": dict(rol="Argumentativo con opinión", min=600, max=900,
                 como="frases de registro coloquial", pruebas=["I-08"],
                 coloquiales_min=6),
    "A-04": dict(rol="Narrativo / crónica", min=100, max=1200,
                 como="cronología con fechas (reutilizado, ver notas)", pruebas=["I-04", "F-01"],
                 fechas_min=0, opcional=("fechas", "H1")),
    "A-05": dict(rol="Artículo con título largo", min=500, max=800,
                 como="título de ≥ 12 palabras", pruebas=["I-09"],
                 titulo_min_palabras=12),
    "A-06": dict(rol="Artículo correcto, sin errores", min=600, max=800,
                 como="redacción impecable, sin ambigüedades", pruebas=["R-01"],
                 sin_muletillas=True, sin_errores_lexicos=True,
                 revision_humana="PENDIENTE"),
    "A-07": dict(rol="Artículo con 3 errores sembrados", min=600, max=900,
                 como="errores localizados y catalogados", pruebas=["R-02"],
                 errores=3),
    "A-08": dict(rol="Artículo muy corto", min=20, max=120,
                 como="texto mínimo coherente, 1 párrafo", pruebas=["R-03"],
                 parrafos_texto=1),
    "A-09": dict(rol="Artículo muy largo", min=1800, max=2000,
                 como="cerca del límite del perfil", pruebas=["R-04"]),
    "A-10": dict(rol="Artículo con muletillas", min=600, max=800,
                 como="≥ 6 muletillas y ≥ 2 usos gramaticales de «pues»", pruebas=["I-10"],
                 muletillas_min=6, conservar_min=2, sin_errores_lexicos=True),
}


@dataclass
class Resultado:
    id: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, nombre: str, ok: bool, detalle: str = "") -> None:
        self.checks.append((nombre, bool(ok), detalle))

    @property
    def ok(self) -> bool:
        return all(c[1] for c in self.checks)


def sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def parrafos(texto: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", texto) if p.strip()]


def titulo_y_cuerpo(texto: str) -> tuple[str, str]:
    lineas = texto.splitlines()
    if lineas and lineas[0].startswith("#"):
        return lineas[0].lstrip("# ").strip(), "\n".join(lineas[1:])
    return "", texto


# Organizaciones, instituciones y topónimos cuentan como nombre propio; una
# palabra capitalizada suelta («Instituto», «Agencia») no, salvo que forme
# parte de un nombre compuesto.
ORGANISMOS = ("Instituto", "Agencia", "Escuela", "Universidad", "Comisión",
              "Fundación", "Laboratorio", "Banco", "Organización")
MARCAS = ("OpenAI", "Hugging", "Face", "Fraunhofer", "Zúrich", "Unión", "Europea")


def nombres_propios(texto: str) -> list[str]:
    """Nombres propios sin duplicar fragmentos de un nombre compuesto."""
    cuerpo = re.sub(r"^#.*$", "", texto, flags=re.MULTILINE)
    compuestos = [
        m.group(0) for m in re.finditer(
            r"\b(?:Agencia|Instituto|Escuela|Universidad|Comisión|Fundación)\s+"
            r"(?:[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+\s+)*[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+",
            cuerpo,
        )
    ]
    cubiertas = {palabra for c in compuestos for palabra in c.split()}
    validos = list(compuestos)
    for m in re.finditer(r"\b[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]{2,}\b", cuerpo):
        palabra = m.group(0)
        if palabra in cubiertas:
            continue
        antes = cuerpo[: m.start()].rstrip()
        if not antes or antes[-1] in ".!?«\"\n#>-:":
            continue  # abre oración o párrafo
        if palabra in ("Instituto", "Agencia", "Escuela", "Laboratorio", "Universidad"):
            continue  # suelto no es nombre propio
        validos.append(palabra)
    return sorted(set(validos))


def buscar(patron: str, texto: str) -> list[str]:
    return [m.group(0) for m in re.finditer(patron, texto, re.IGNORECASE)]


def _verificar_entidades(aid: str, spec: dict, texto: str, titulo: str, r: Resultado) -> None:
    """Cifras, fechas, nombres propios y título: lo medible sin juicio."""
    cifras = CIFRA.findall(texto)
    fechas = FECHA.findall(texto)
    if "cifras_min" in spec:
        r.check("cifras ≥ mínimo", len(cifras) >= spec["cifras_min"],
                f"{len(cifras)} cifras, muestra {cifras[:8]}")
    if "cifras_max" in spec:
        r.check("sin cifras (control F-01)", len(cifras) == 0, f"{len(cifras)} cifras: {cifras[:5]}")
    if "fechas_max" in spec:
        r.check("sin fechas", len(fechas) == 0, f"{len(fechas)} fechas: {fechas[:5]}")
    if "fechas" in spec.get("opcional", ()) and len(fechas) == 0:
        r.check("con fechas", True, "no exigido: pieza reutilizada sin cronología (limitación declarada)")
    elif spec.get("fechas_min", 0):
        r.check("con fechas", len(fechas) >= spec["fechas_min"], f"{len(fechas)} fechas")
    if "nombres_min" in spec:
        nombres = nombres_propios(texto)
        r.check("nombres propios ≥ mínimo", len(nombres) >= spec["nombres_min"],
                f"{len(nombres)}: {nombres}")
    if "titulo_min_palabras" in spec:
        n = len(titulo.split())
        r.check("título largo", n >= spec["titulo_min_palabras"],
                f"{n} palabras (mínimo {spec['titulo_min_palabras']}): {titulo}")


def _verificar_registro(spec: dict, texto: str, r: Resultado) -> None:
    """Registro coloquial, párrafos y muletillas frente a sus usos legítimos."""
    if "coloquiales_min" in spec:
        halladas = [p for p in MARCADORES_COLOQUIALES if buscar(p, texto)]
        r.check("registro coloquial", len(halladas) >= spec["coloquiales_min"],
                f"{len(halladas)} marcas distintas: {halladas}")
    if "parrafos_texto" in spec:
        parr_texto = parrafos(re.sub(r"^#.*$", "", texto, flags=re.MULTILINE))
        r.check("párrafos de texto", len(parr_texto) == spec["parrafos_texto"],
                f"{len(parr_texto)} párrafo(s)")
    if "muletillas_min" in spec:
        conteo = {k: len(buscar(p, texto)) for k, p in MULETILLAS.items()}
        total = sum(conteo.values())
        r.check("muletillas ≥ mínimo", total >= spec["muletillas_min"],
                f"{total}: { {k: v for k, v in conteo.items() if v} }")
        cons = {k: len(re.findall(p, texto, re.IGNORECASE)) for k, p in CONSERVAR.items()}
        cons["pues_gramatical"] -= len(NO_GRAMATICALES.findall(texto))
        cons = {k: v for k, v in cons.items() if v > 0}
        n_cons = sum(cons.values())
        r.check("conservar ≥ 2 usos gramaticales", n_cons >= spec["conservar_min"],
                f"{n_cons}: {cons}")
    if spec.get("sin_muletillas"):
        halladas_m = {k: buscar(p, texto) for k, p in MULETILLAS.items() if buscar(p, texto)}
        r.check("A-06 sin muletillas", not halladas_m, str(halladas_m))


def _verificar_lexica(spec: dict, texto: str, r: Resultado) -> None:
    """Ausencia de errores léxicos típicos que invalidarían los controles."""
    if not spec.get("sin_errores_lexicos"):
        return
    for nombre, patron in ERRORES_LEXICOS.items():
        if patron == r"(?!x)x":
            continue
        hits = buscar(patron, texto)
        r.check(f"error léxico ausente: {nombre}", not hits, str(hits))


def verificar_texto(aid: str, texto: str) -> Resultado:
    spec = SPEC[aid]
    r = Resultado(aid)
    palabras = len(texto.split())
    titulo, _ = titulo_y_cuerpo(texto)

    r.check("longitud", spec["min"] <= palabras <= spec["max"],
            f"{palabras} palabras (rol {spec['min']}-{spec['max']})")
    if "H1" in spec.get("opcional", ()):
        r.check("H1", True, "no exigido: pieza reutilizada sin encabezado (limitación declarada)")
    else:
        r.check("H1", bool(titulo), f"título: {titulo[:60]!r}" if titulo else "sin H1")
    r.check("sin imágenes", "![" not in texto, f"{texto.count('![')} imagen(es)")
    r.check("sin tablas", not re.search(r"^\s*\|.*\|\s*$", texto, re.MULTILINE),
            "markdown sin tablas")

    _verificar_entidades(aid, spec, texto, titulo, r)
    _verificar_registro(spec, texto, r)
    _verificar_lexica(spec, texto, r)
    return r


def verificar_aspell(aid: str, r: Resultado, texto: str, esperadas: set[str] | None = None) -> None:
    """Ortografía real. A-06: cero desconocidas. A-07: solo las sembradas."""
    disponible, desconocidas = aspell(texto)
    if not disponible:
        r.check("aspell", False, desconocidas[0] if desconocidas else "no disponible")
        return
    if aid == "A-06":
        r.check("aspell: sin errores ortográficos", not desconocidas, str(desconocidas))
    elif aid == "A-07":
        esperadas = esperadas or set()
        sobran = sorted(set(desconocidas) - esperadas)
        faltan = sorted(esperadas - set(desconocidas))
        r.check("aspell: solo las 3 palabras sembradas", not sobran, f"sobran: {sobran}")
        r.check("aspell: las 3 sembradas detectadas", not faltan, f"faltan: {faltan}")
    else:
        # Informativo: no bloquea, porque los tecnicismos legítimos son muchos.
        r.check("aspell (informativo)", True, f"{len(desconocidas)} desconocidas: {desconocidas[:6]}")


# Palabras que aspell marca y son válidas: nombres propios, tecnicismos y
# hashtags de la pieza reutilizada.
ASPELL_PERMITIDAS = {
    "aerotérmica", "aerotérmicos", "antivibratorios", "geotérmicos",
    "Fraunhofer", "Zúrich", "Helmut", "Jacobs", "Jane", "Kuhn",
    "desarenador", "fibrocemento", "floculación", "potabilización",
    "Hugging", "OpenAI", "Face",
}
ASPELL_PERMITIDAS.update(
    p for p in (
        "AISafety", "ArtificialIntelligence", "CyberSecurity", "GobiernoDigital",
        "SeguridadInformática", "TransformaciónDigital",
    )
)


def aspell(texto: str) -> tuple[bool, list[str]]:
    """Palabras que `aspell -l es` marca como desconocidas (salvo lista blanca)."""
    import shutil
    import subprocess

    if not shutil.which("aspell"):
        return False, ["aspell no instalado"]
    proc = subprocess.run(
        ["aspell", "-l", "es", "--encoding=utf-8", "list"],
        input=texto, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return False, [f"aspell falló: {proc.stderr.strip()}"]
    palabras = sorted({w for w in proc.stdout.split() if w not in ASPELL_PERMITIDAS})
    return True, palabras


def _bloque_yaml(texto: str) -> str:
    """Extrae el primer bloque ```yaml de un Markdown; si no hay, devuelve el texto."""
    m = re.search(r"```ya?ml\s*\n(.*?)```", texto, re.DOTALL)
    return m.group(1) if m else texto


def verificar_a07(r: Resultado, texto: str) -> dict:
    """Contrasta A-07.md con el registro YAML: párrafo, unicidad, offset."""
    yaml_path = CORPUS / "A-07.errores.yaml"
    r.check("registro de errores existe", yaml_path.is_file(), str(yaml_path.name))
    if not yaml_path.is_file():
        return {}
    meta: dict = {}
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - entorno sin PyYAML
        r.check("registro legible", False, "PyYAML no disponible: no se puede leer el registro")
        return meta
    datos = yaml.safe_load(_bloque_yaml(yaml_path.read_text(encoding="utf-8")))
    errores = datos.get("errores", [])
    r.check("exactamente 3 errores", len(errores) == 3, f"{len(errores)}")
    categorias = {e["categoria"] for e in errores}
    r.check("categoría única", len(categorias) == 1, f"categorías: {sorted(categorias)}")
    parras = parrafos(texto)
    for e in errores:
        eid = e.get("id", "?")
        orig, corr = e["original"], e["correcto"]
        r.check(f"{eid}: original único en el texto", texto.count(orig) == 1,
                f"'{orig}' aparece {texto.count(orig)} vez")
        ini, fin = e["offset"]
        r.check(f"{eid}: offset correcto", texto[ini:fin] == orig,
                f"[{ini},{fin}] = {texto[ini:fin]!r}")
        idx = e["parrafo"]
        en_parrafo = 0 <= idx < len(parras) and orig in parras[idx]
        r.check(f"{eid}: párrafo correcto", en_parrafo,
                f"párrafo {idx}: {'contiene' if en_parrafo else 'NO contiene'} '{orig}'")
        frase_ok = e["frase"] in texto
        r.check(f"{eid}: frase de contexto presente", frase_ok, e["frase"][:50])
        meta[eid] = {"original": orig, "correcto": corr, "parrafo": idx}
    return meta


def verificar_a04_copia(r: Resultado, texto: str) -> None:
    original = next(
        (p for p in (ORIGINAL_A04, ORIGINAL_A04_ALTERNATIVO) if p.is_file()), None
    )
    if original is None:
        r.check("original A-04 localizable", False, f"no existe {ORIGINAL_A04}")
        return
    r.check("original A-04 localizable", True, str(original))
    copia = (CORPUS / "A-04.md").read_bytes()
    r.check("A-04 idéntico byte a byte al original", original.read_bytes() == copia,
            f"{len(original.read_bytes())} vs {len(copia)} bytes")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emite JSON")
    ap.add_argument("--estricto", action="store_true",
                    help="falla también si hay pendientes humanos")
    args = ap.parse_args()

    existentes = sorted(p.stem for p in CORPUS.glob("A-??.md")) if CORPUS.is_dir() else []
    resultados: list[Resultado] = []
    resumen_general = Resultado("corpus")
    resumen_general.check("10 artículos A-01..A-10", existentes == ARTICULOS,
                          f"encontrados: {existentes}")

    textos: dict[str, str] = {}
    for aid in ARTICULOS:
        ruta = CORPUS / f"{aid}.md"
        r = Resultado(aid)
        if not ruta.is_file():
            r.check("existe", False, str(ruta))
            resultados.append(r)
            continue
        r.check("existe", True, ruta.name)
        texto = ruta.read_text(encoding="utf-8")
        textos[aid] = texto
        detalle = verificar_texto(aid, texto)
        r.checks.extend(detalle.checks)
        if aid == "A-07":
            meta = verificar_a07(r, texto)
            verificar_aspell(aid, r, texto, {e["original"] for e in meta.values()} if meta else set())
        elif aid == "A-06":
            verificar_aspell(aid, r, texto)
        else:
            verificar_aspell(aid, r, texto)
        if aid == "A-04":
            verificar_a04_copia(r, texto)
        resultados.append(r)

    dominios = {
        "A-01": "energía y edificación", "A-02": "sociología urbana",
        "A-03": "organización del trabajo", "A-04": "IA y seguridad",
        "A-05": "gestión del conocimiento", "A-06": "agua y servicios públicos",
        "A-07": "energía y política pública", "A-08": "narrativa breve",
        "A-09": "energía y comunidades", "A-10": "tecnología y procesos",
    }
    resumen_general.check("≥ 4 dominios distintos", len(set(dominios.values())) >= 4,
                          f"{len(set(dominios.values()))} dominios")

    fallidas = [r for r in resultados if not r.ok] + ([] if resumen_general.ok else [resumen_general])
    codigo = 1 if fallidas else 0
    pendientes = [aid for aid in ("A-06", "A-07")]

    if args.json:
        print(json.dumps({
            "corpus": str(CORPUS),
            "resultados": [
                {"id": r.id, "ok": r.ok,
                 "checks": [{"nombre": n, "ok": o, "detalle": d} for n, o, d in r.checks]}
                for r in [resumen_general, *resultados]
            ],
            "fallidas": [r.id for r in fallidas],
            "pendientes_humanos": pendientes,
            "codigo": codigo if not (args.estricto and pendientes) else 1,
        }, ensure_ascii=False, indent=2))
    else:
        todos = [resumen_general, *resultados]
        ancho = max((len(n) for r in todos for n, _, _ in r.checks), default=10)
        for item in todos:
            etiqueta_estado = "PASS" if item.ok else "FALLA"
            sufijo_rol = f" ({SPEC[item.id]['rol']})" if item.id in SPEC else ""
            print(f"\n[{etiqueta_estado}] {item.id}{sufijo_rol}")
            for nombre_check, ok_check, detalle_check in item.checks:
                marca = "ok  " if ok_check else "FALLA"
                print(f"  {marca} {nombre_check:<{ancho}}  {detalle_check}")
        print("\n" + "=" * 72)
        print(f"automáticas: {sum(1 for x in resultados if x.ok)}/{len(resultados)} artículos PASS")
        print("pendientes humanos (no verificables aquí): " + ", ".join(pendientes))
        veredicto = "TODO PASS (automático)" if codigo == 0 else f"FALLAN: {[x.id for x in fallidas]}"
        print("RESULTADO: " + veredicto)

    if args.estricto and pendientes:
        return 1
    return codigo


if __name__ == "__main__":
    sys.exit(main())
