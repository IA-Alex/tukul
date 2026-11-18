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

Fidelidad con la aplicación: el SYSTEM_PROMPT, el prompt de usuario (vía
`build_editor_prompt`) y el parser de vuelta son EXACTAMENTE los de producción.
El muestreo, en cambio, difiere a propósito: este adaptador fija
`temperature=0` y `seed=7` para que un PASS/FAIL no dependa del azar del modelo
(ver el comentario del cuerpo). El cliente de producto envía
`profile.temperature` (0.5 por defecto) y no manda `seed`. El eval mide, por
tanto, la calidad del prompt y del parser ante un muestreo determinista, no el
request byte a byte de la aplicación.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from tukul_core.llm import LLMClient  # noqa: E402
from tukul_core.models import ChatMessage, LlmProfile  # noqa: E402
from tukul_core.prompting import build_editor_prompt  # noqa: E402
from tukul_core.prompts import MODO_POR_DEFECTO, prompt_sistema  # noqa: E402
from tukul_core.review import diagnose_findings, omitted_reasons  # noqa: E402

ENDPOINT = os.environ.get(
    "TUKUL_EVAL_ENDPOINT", "https://api.deepinfra.com/v1/openai/chat/completions"
)
MODELO = os.environ.get("TUKUL_EVAL_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731")
VARIABLE_KEY = os.environ.get("TUKUL_EVAL_API_KEY_ENV", "DEEPINFRA_API_KEY")
TIMEOUT = 120
# Reintentos ante un proveedor saturado. DeepInfra devuelve 429 «Model busy»
# sin `Retry-After`; con presupuesto bajo (por defecto 6 intentos, backoff
# exponencial acotado con jitter) el eval convierte un pico de carga en un caso
# lento pero válido, en vez de en un fallo que envenena el veredicto. Un número
# mayor encarece la corrida cuando el proveedor está caído de verdad.
MAX_INTENTOS = int(os.environ.get("TUKUL_EVAL_MAX_INTENTOS", "6"))
BACKOFF_BASE = 2.0
BACKOFF_MAX = 30.0
# Códigos que SÍ se reintentan: el proveedor está ocupado o inestable, no hay
# nada que corregir en la petición. 401/403 quedan fuera a propósito: son
# credencial, y reintentarlas solo alarga el fallo.
CODIGOS_REINTENTABLES = {408, 429, 500, 502, 503, 504}



class CredencialInvalidaError(RuntimeError):
    """La credencial del eval no sirve: hay que renovarla, no depurar el código."""


class ProveedorOcupadoError(RuntimeError):
    """El proveedor siguió «ocupado» (429) agotado el presupuesto de reintentos.

    DeepInfra responde `429 {"error":{"message":"Model busy, retry later"}}` sin
    `Retry-After` cuando está saturado. Sin reintentos, cada 429 se cuenta como
    un fallo del caso: se midió una batería a 9/24 con 15 de esos fallos siendo
    429, no contrato. Distinguirlo de `CredencialInvalidaError` mantiene legible
    el motivo real del fallo.
    """


def _redactar(texto: str, clave: str) -> str:
    """Quita la key de cualquier texto que vaya a la salida del eval."""
    return texto.replace(clave, "***") if clave else texto


def _forma_de_revision(salida: str) -> str:
    """Clasifica la forma de la respuesta sin reinterpretar el contrato.

    Valores:
    - ``findings``: trae el contrato mínimo (`{"findings": [...]}` o array raíz).
    - ``vacia``: trae `findings` como lista vacía; revisión legítima.
    - ``otra``: es JSON del objeto, pero sin `findings` (p. ej. `{"review": …}`).
    - ``prosa``: no hay JSON decodificable.

    No sustituye a `diagnose_findings`: solo añade el matiz que su causa
    `sin_hallazgos` no puede distinguir. El caso `{"review": …}` se observó el
    2026-11-16 y colapsaba con «artículo limpio», que es un PASS.
    """
    causa, _hallazgos = diagnose_findings(salida)
    if causa == "ok":
        return "findings"
    if causa == "sin_hallazgos":
        return "vacia"
    if causa == "esquema_ajeno" and salida.strip().startswith("{"):
        return "otra"
    return "prosa"


def _temperatura() -> float:
    """Temperatura del eval: 0 por defecto, configurable por entorno.

    Un valor mal escrito no debe romper el eval silenciosamente: se cae al 0
    determinista y se avisa por stderr (promptfoo lo muestra con el caso).
    """
    bruto = os.environ.get("TUKUL_EVAL_TEMPERATURE", "0")
    try:
        valor = float(bruto)
    except ValueError:
        print(f"[eval] TUKUL_EVAL_TEMPERATURE inválida ({bruto!r}); uso 0", file=sys.stderr)
        return 0.0
    if not 0.0 <= valor <= 2.0:
        print(f"[eval] TUKUL_EVAL_TEMPERATURE fuera de rango ({valor}); uso 0", file=sys.stderr)
        return 0.0
    return valor


def _usar_streaming() -> bool:
    """¿El eval debe medir por streaming? `TUKUL_EVAL_STREAM` (dinámico).

    Se lee en cada llamada, no al importar: los tests y el operador pueden
    cambiarla por caso. Modelos de razonamiento como `Qwen/Qwen3.5-9B` de
    DeepInfra devuelven vacío o cortan la conexión en no-streaming y solo
    responden bien por SSE; forzar no-streaming los mediría con salida vacía y
    convertiría cada caso en un fallo del modelo, no del contrato.
    """
    return os.environ.get("TUKUL_EVAL_STREAM", "").strip().lower() in {"1", "true", "yes", "si", "sí"}


def _llamar_streaming(prompt_sistema: str, prompt_usuario: str, clave: str) -> str:
    """Llama por streaming reusando el `LLMClient` real del repo.

    No reimplementa el parseo SSE: el cliente de producción ya lo hace y está
    probado. Así el eval mide el mismo transporte que la app. `LlmProfile` se
    construye con el endpoint/modelo del eval; `temperature` y `seed` del
    adaptador no viajan aquí porque `LLMClient` no expone esos campos en el
    perfil, así que en streaming el muestreo lo fija el proveedor.
    """
    perfil = LlmProfile(
        provider="openai_compatible",
        endpoint=ENDPOINT,
        model=MODELO,
        max_output_tokens=1024,
    )
    # Los modelos de razonamiento tardan más que `HTTP_TIMEOUT_SECONDS` (90 s) en
    # una revisión completa. Se permite ampliarlo SOLO en el proceso del eval,
    # sin tocar el valor de producción, para no cortar a mitad una respuesta
    # válida que el modelo aún está escribiendo.
    timeout = os.environ.get("TUKUL_EVAL_HTTP_TIMEOUT")
    if timeout:
        import tukul_core.llm as _llm

        _llm.HTTP_TIMEOUT_SECONDS = float(timeout)
    cliente = LLMClient()
    partes: list[str] = []
    for chunk in cliente.stream(perfil, clave, prompt_usuario, modo=None):
        if chunk.content:
            partes.append(chunk.content)
    return "".join(partes)


def _llamar(prompt_sistema: str, prompt_usuario: str, clave: str) -> str:
    """Llama al proveedor por el transporte que pida `TUKUL_EVAL_STREAM`.

    Sin streaming (por defecto) preserva el comportamiento histórico y el
    muestreo determinista (`temperature=0`, `seed=7`). Con streaming delega en
    `_llamar_streaming`, que usa el `LLMClient` real: es la única forma de medir
    modelos que solo responden por SSE.
    """
    if _usar_streaming():
        return _llamar_streaming(prompt_sistema, prompt_usuario, clave)
    return _llamar_sin_streaming(prompt_sistema, prompt_usuario, clave)


def _llamar_sin_streaming(prompt_sistema: str, prompt_usuario: str, clave: str) -> str:
    cuerpo = json.dumps({
        "model": MODELO,
        # Temperatura 0 por defecto: un eval que se lee como PASS/FAIL necesita
        # que la única variable sea el prompt. Con 0.2 el mismo caso daba 7/8 y
        # 8/8 en ejecuciones distintas, y el fallo no distinguía un defecto del
        # sistema de la aleatoriedad del modelo.
        #
        # `TUKUL_EVAL_TEMPERATURE` permite medir el riesgo residual: el producto
        # envía `profile.temperature` (0.5 por defecto), así que correr el eval
        # con 0.5 responde «¿la calidad se sostiene con el muestreo real?». Ese
        # modo NO sustituye al determinista: añade la varianza del modelo y sirve
        # para saber si el PASS es robusto, no para aislar el prompt.
        "temperature": _temperatura(),
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
    ultimo_429: urllib.error.HTTPError | None = None
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise CredencialInvalidaError(
                    f"El proveedor rechazó la credencial (HTTP {error.code}): revisa que "
                    f"${VARIABLE_KEY} siga siendo válida y no esté revocada."
                ) from error
            if error.code not in CODIGOS_REINTENTABLES or intento == MAX_INTENTOS:
                if error.code == 429:
                    ultimo_429 = error
                    break
                raise
            _esperar_reintento(error, intento)
    else:  # el bucle siempre sale por break/raise; defensivo
        raise ProveedorOcupadoError("No se pudo contactar con el proveedor del eval.")

    if ultimo_429 is not None:
        raise ProveedorOcupadoError(
            f"El proveedor siguió ocupado (HTTP 429) tras {MAX_INTENTOS} intentos; "
            "la corrida no puede medir el contrato con este nivel de saturación."
        ) from ultimo_429

    contenido = datos["choices"][0]["message"]["content"]
    return str(contenido)


def _esperar_reintento(error: urllib.error.HTTPError, intento: int) -> None:
    """Espera antes del siguiente intento, respetando `Retry-After` si viene.

    DeepInfra hoy no manda `Retry-After` («Model busy»), así que el respaldo es
    un backoff exponencial acotado con jitter para no sincronizar varios casos
    contra el mismo pico de carga.
    """
    retry_after = error.headers.get("Retry-After") if error.headers else None
    if retry_after is not None:
        try:
            espera = min(max(float(retry_after), 0.0), BACKOFF_MAX)
        except (TypeError, ValueError):
            espera = min(BACKOFF_BASE * (2 ** (intento - 1)), BACKOFF_MAX)
    else:
        espera = min(BACKOFF_BASE * (2 ** (intento - 1)), BACKOFF_MAX)
    jitter = espera * 0.25 * random.random()
    print(f"[eval] {error.code} del proveedor; reintento {intento}/{MAX_INTENTOS} "
          f"en {espera + jitter:.1f}s", file=sys.stderr)
    time.sleep(espera + jitter)



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
    # Modo del prompt de sistema. Por defecto `revision`, que es lo que miden
    # estos evals; un caso puede pedir otro modo con `vars.mode`. Antes el
    # adaptador importaba el re-export fijo `SYSTEM_PROMPT` (= prompt de
    # revisión), así que no podía ejercitar los otros modos pese a afirmar que
    # medía «lo que la aplicación envía de verdad» (defecto H-4).
    modo = str(vars_.get("mode") or MODO_POR_DEFECTO)

    clave = os.environ.get(VARIABLE_KEY, "")
    if not clave:
        # Sin key no se llama al proveedor: el eval debe fallar con un motivo
        # legible, no con un traceback de red.
        print(json.dumps({
            "output": "",
            "error": f"Falta la variable de entorno {VARIABLE_KEY}",
        }))
        return 0

    # El prompt de usuario replica el de la aplicación para el modo pedido: en
    # revisión, el prompt técnico de revisión precede a la conversación.
    from tukul_ui.app import REVIEW_PROMPT  # import diferido: arrastra Tk

    conversacion_con_revision = [ChatMessage("user", REVIEW_PROMPT), *conversacion]
    prompt_usuario = build_editor_prompt(articulo, contexto, conversacion_con_revision)

    try:
        inicio = time.monotonic()
        salida = _llamar(prompt_sistema(modo), prompt_usuario, clave)
        latencia_ms = int((time.monotonic() - inicio) * 1000)
    except CredencialInvalidaError as error:
        print(json.dumps({"output": "", "error": _redactar(str(error), clave)}))
        return 0
    except ProveedorOcupadoError as error:
        # Distinto de un fallo del contrato: el veredicto de la corrida es
        # INCONCLUYENTE por saturación del proveedor, y el mensaje debe decirlo.
        print(json.dumps({"output": "", "error": _redactar(str(error), clave)}))
        return 0
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(json.dumps({"output": "", "error": _redactar(str(error), clave)}))
        return 0
    except (KeyError, IndexError, ValueError) as error:
        print(json.dumps({"output": "", "error": f"respuesta inesperada: {error}"}))
        return 0

    causa, hallazgos = diagnose_findings(salida)
    # `sin_hallazgos` cubre dos situaciones que el contrato distingue pero el
    # parser colapsa a propósito: la lista vacía (revisión legítima) y una
    # respuesta con forma de revisión pero sin `findings` (p. ej.
    # `{"review": "…"}`, observado el 2026-11-16). La primera es un PASS; la
    # segunda significa que el modelo no entregó las citas y el caso debe
    # contar como fallo del modelo, no como «artículo limpio». El eval no
    # puede leer esa diferencia si no se publica aquí.
    forma = _forma_de_revision(salida)
    print(json.dumps({
        "output": _redactar(salida, clave),
        "metadata": {
            # El parser REAL del repo decide esto, igual que en la aplicación.
            "parse_findings_count": len(hallazgos),
            # La CAUSA distingue «sin hallazgos» (éxito) de «sin JSON» o
            # «esquema ajeno» (fallo), que colapsan en count=0. Las aserciones
            # deben mirar esto, no solo el conteo.
            "parse_cause": causa,
            # Distingue «revisión vacía declarada» (`findings: []`) de «el
            # modelo no devolvió el contrato». Solo es informativo para el
            # parser; las aserciones pueden rechazar el segundo caso.
            "review_shape": forma,
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
            # Modo del prompt de sistema con el que se midió: permite ver, en el
            # reporte, que un caso no cayó en el prompt de revisión por descuido.
            "prompt_mode": modo,
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
