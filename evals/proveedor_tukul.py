#!/usr/bin/env python3
"""Adaptador de promptfoo para Tukul: llama al REPO, no a una copia del prompt.

Promptfoo ejecuta este archivo como `exec` provider (ver promptfooconfig.yaml).
Se ejecuta con el intérprete del proyecto (`.venv/bin/python`) porque necesita
`tukul_core`. Configuración por variable de entorno, nunca en el YAML:

- `TUKUL_EVAL_ENDPOINT`      endpoint (por defecto, el de tukul.example.toml)
- `TUKUL_EVAL_MODEL`         modelo (por defecto DeepInfra/DeepSeek V4 Flash)
- `TUKUL_EVAL_API_KEY_ENV`   NOMBRE de la variable que contiene la key
                             (por defecto `DEEPINFRA_API_KEY`)

Entrada: el prompt renderizado llega como PRIMER ARGUMENTO (contrato de
`exec:` de promptfoo) y, si no hay argumento, por stdin como JSON:
{"vars": {...}}. Salida JSON por stdout:
{"output": "<texto crudo del modelo>", "metadata": {...}}.

Así el eval mide lo que la aplicación envía de verdad (`SYSTEM_PROMPT`,
`build_editor_prompt`) y lo que de verdad acepta al volver (`parse_findings`).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from tukul_core.llm import SYSTEM_PROMPT  # noqa: E402
from tukul_core.models import ChatMessage  # noqa: E402
from tukul_core.prompting import build_editor_prompt  # noqa: E402
from tukul_core.review import omitted_reasons, parse_findings  # noqa: E402

ENDPOINT = os.environ.get(
    "TUKUL_EVAL_ENDPOINT", "https://api.deepinfra.com/v1/openai/chat/completions"
)
MODELO = os.environ.get("TUKUL_EVAL_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
VARIABLE_KEY = os.environ.get("TUKUL_EVAL_API_KEY_ENV", "DEEPINFRA_API_KEY")
TIMEOUT = 120


def _redactar(texto: str, clave: str) -> str:
    """Quita la key de cualquier texto que vaya a la salida del eval."""
    return texto.replace(clave, "***") if clave else texto


def _llamar(prompt_sistema: str, prompt_usuario: str, clave: str) -> str:
    cuerpo = json.dumps({
        "model": MODELO,
        # Temperatura 0: un eval que se lee como PASS/FAIL necesita que la
        # única variable sea el prompt. Con 0.2 el mismo caso daba 7/8 y 8/8
        # en ejecuciones distintas, y el fallo no distinguía un defecto del
        # sistema de la aleatoriedad del modelo.
        "temperature": 0,
        # Semilla fija: además de temperature 0, acota el remuestreo del
        # proveedor cuando lo soporta (DeepInfra lo ignora si no aplica).
        "seed": 7,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": prompt_usuario},
        ],
    }).encode("utf-8")
    peticion = urllib.request.Request(
        ENDPOINT,
        data=cuerpo,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {clave}",
        },
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    contenido = datos["choices"][0]["message"]["content"]
    return str(contenido)


SEPARADOR_TURNOS = "\n---\n"


def _turnos_previos(vars_: dict) -> list[str]:
    """Devuelve los turnos previos como lista de strings.

    Promptfoo EXPANDE las variables de tipo lista: un `vars.conversation` con
    dos elementos se convierte en DOS tests, y cada uno recibe un único string.
    Por eso `conversation` no puede ser una lista aquí — si se itera un string,
    se parte carácter por carácter (bug observado: 47 turnos de una letra).

    Se aceptan las dos formas:
    - string con turnos separados por `\\n---\\n` (la que usa el YAML);
    - lista (por si el adaptador se invoca en seco desde stdin).
    """
    valor = vars_.get("conversation", [])
    if isinstance(valor, str):
        return [t.strip() for t in valor.split(SEPARADOR_TURNOS) if t.strip()]
    if isinstance(valor, list):
        return [str(t) for t in valor]
    return []


def _leer_entrada(args: list[str]) -> dict:
    """Devuelve `{"vars": ...}` desde el argumento de promptfoo o desde stdin.

    Contrato de `exec:`: el prompt renderizado llega como primer argumento. En
    este eval el prompt es `{{article}}`, así que ese argumento ES el artículo
    y la configuración viaja por `options` (segundo argumento) y el entorno.
    El modo stdin se conserva para poder probar el adaptador en seco.
    """
    if len(args) >= 2:
        # (prompt, options_json, context_json)
        try:
            contexto = json.loads(args[2]) if len(args) >= 3 else {}
        except json.JSONDecodeError:
            contexto = {}
        vars_ = dict(contexto.get("vars") or {})
        vars_.setdefault("article", args[0])
        return {"vars": vars_}
    if len(args) == 1:
        return {"vars": {"article": args[0]}}
    entrada = json.load(sys.stdin)
    return dict(entrada) if isinstance(entrada, dict) else {}


def main() -> int:
    try:
        peticion = _leer_entrada(sys.argv[1:])
    except json.JSONDecodeError:
        print(json.dumps({"error": "stdin debe ser JSON"}))
        return 1

    vars_ = peticion.get("vars") or {}
    articulo = vars_.get("article", "")
    contexto = vars_.get("context", "")
    conversacion = [ChatMessage("user", m) for m in _turnos_previos(vars_)]

    clave = os.environ.get(VARIABLE_KEY, "")
    if not clave:
        # Sin key no se llama al proveedor: el eval debe fallar con un motivo
        # legible, no con un traceback de red.
        print(json.dumps({
            "output": "",
            "error": f"Falta la variable de entorno {VARIABLE_KEY}",
        }))
        return 0

    # El prompt de revisión es el mismo que envía la aplicación.
    from tukul_ui.app import REVIEW_PROMPT  # import diferido: arrastra Tk

    conversacion_con_revision = [ChatMessage("user", REVIEW_PROMPT), *conversacion]
    prompt_usuario = build_editor_prompt(articulo, contexto, conversacion_con_revision)

    try:
        inicio = time.monotonic()
        salida = _llamar(SYSTEM_PROMPT, prompt_usuario, clave)
        latencia_ms = int((time.monotonic() - inicio) * 1000)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(json.dumps({"output": "", "error": _redactar(str(error), clave)}))
        return 0
    except (KeyError, IndexError, ValueError) as error:
        print(json.dumps({"output": "", "error": f"respuesta inesperada: {error}"}))
        return 0

    hallazgos = parse_findings(salida)
    print(json.dumps({
        "output": _redactar(salida, clave),
        "metadata": {
            # El parser REAL del repo decide esto, igual que en la aplicación.
            "parse_findings_count": len(hallazgos),
            "parse_findings_categories": sorted({h["category"] for h in hallazgos}),
            # Motivos que el modelo declara haber omitido a petición del usuario:
            # permite distinguir una revisión vacía legitima de una obediencia.
            "omitted_reasons": omitted_reasons(salida),
            # Tamaño de la respuesta y tiempo de pared: la calidad no sirve si
            # una revisión tarda 30 s o devuelve 400 KB, y sin medirlo el eval
            # solo podía opinar sobre el contenido.
            "response_chars": len(salida),
            "latency_ms": latencia_ms,
            "endpoint": ENDPOINT,
            "model": MODELO,
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
