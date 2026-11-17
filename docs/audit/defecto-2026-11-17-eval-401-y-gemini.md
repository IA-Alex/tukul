# Defecto del 2026-11-17 — eval `401` opaco y transporte Gemini sin defensa

Sesión del 2026-11-17. Skills: `reparador-integral-es` + `test-driven-development` +
`debug-live`. Ver [`POLITICA_CONGELACION.md`](../POLITICA_CONGELACION.md): ambos
puntos son un **defecto confirmado** y un **retiro sin consumidor**, así que abren
parche `0.8.3`.

## Baseline

| Comprobación | Comando | Resultado |
|---|---|---|
| Suite completa | `xvfb-run -a .venv/bin/python -m pytest -q` | 892 passed |
| Lint | `.venv/bin/python -m ruff check .` | limpio |
| Tipos | `.venv/bin/python -m mypy tukul_core tukul_ui tukul.py` | limpio, 69 archivos |
| Health | `.venv/bin/python tukul.py --health` | OK |
| Eval base | `npx promptfoo eval -c evals/promptfooconfig.yaml` | **0/8 — HTTP 401** |

## Defecto 1 — el `401` no decía que la credencial estaba mal

**Síntoma:** el eval salía 8/8 en rojo con `HTTP Error 401: Unauthorized`.

**Causa raíz:** la credencial de `.env` estaba **revocada** (el endpoint devolvía
`invalid_api_key`), y `evals/proveedor_tukul.py::main` solo traducía
`URLError/TimeoutError/OSError`: un `HTTPError` llegaba crudo como `str(error)`,
indistinguible de un fallo de red o del contrato. — **Evidencia:** llamada directa
al endpoint con la key del `.env` → `HTTP 401 {"code":"invalid_api_key"}`.

**Corrección:** `_llamar` traduce `401`/`403` a `CredencialInvalidaError` con el
nombre de la variable a revisar, sin filtrar la key; `main` la publica como
`error` del eval.

**Regresión:** `tests/test_adaptador_eval.py::
test_una_key_revocada_explica_el_401_en_vez_de_propagarlo_crudo` → FAIL con el
código previo (`AttributeError`), PASS con la corrección.

**Verificación en vivo:** eval base **8/8** con `deepseek-ai/DeepSeek-V4-Flash-0731`.

## Defecto 2 — rama Gemini frágil y sin consumidor

**Causa raíz:** la rama `gemini_generate_content` de `complete` hacía
`data["candidates"][0]["content"]["parts"]` sin defensa; un `candidates[0]` sin
`content` (respuesta bloqueada o truncada) reventaba como «respuesta no válida».
Ningún consumidor de producto la usaba (ADR-0004 la declaraba API programática sin
cableado).

**Corrección:** retirado el transporte completo (`gemini_url`, ramas de `_request`,
`_stream_event` y `complete`) y sincronizados `ARCHITECTURE.md`,
`ARCHITECTURE_DIAGRAM.md` y `ADR-0004`. `anthropic_messages` se mantiene.

## Tabla de impacto

| Componente | Relación | ¿Cambió? | Motivo |
|---|---|---|---|
| `evals/proveedor_tukul.py` | produce la salida del eval | **Sí** | Defecto 1; modelo por defecto |
| `tukul_core/llm.py` | transporta al proveedor | **Sí** | Defecto 2: retiro de Gemini |
| `tests/test_adaptador_eval.py` | prueba | **Sí** | Regresión del 401 |
| `tests/test_llm_http_contract.py` | prueba | **Sí** | Caso Gemini retirado |
| `tests/test_hallazgos_restantes.py` | prueba | **Sí** | Rama Gemini retirada |
| `docs/ARCHITECTURE.md`, `ARCHITECTURE_DIAGRAM.md`, `ADR-0004` | contrato | **Sí** | Dejaban de describir el código |
| `evals/promptfooconfig*.yaml`, `evals/README.md`, `scripts/bateria_modelo.py` | configuración | **Sí** | Modelo `-0731` |
| `tukul_core/prompts.py`, `prompts`, `review.py` | provee prompts/parser | **No** | Sin cambios en el contrato |
| `tukul_ui/*` | consumidor del cliente | **No** | No referenciaba Gemini |
| Traducción de errores de producto (`LlmError`) | consumidor | **No** | Fuera de este defecto |

## Verificación

| Comando | Resultado |
|---|---|
| `xvfb-run -a .venv/bin/python -m pytest -q` | 892 passed |
| `.venv/bin/python -m ruff check .` | All checks passed |
| `.venv/bin/python -m mypy tukul_core tukul_ui tukul.py` | Success, 69 archivos |
| `npx promptfoo eval -c evals/promptfooconfig.yaml --no-cache` | 8/8 |
| `uv lock --check` | limpio (`tukul 0.8.3`) |
| `./scripts/quality-gate.sh` | **✓ QUALITY GATE PASSED** — 892 passed, 926 registradas, 0 omitidas, cobertura 87,62 % |

## Estado

**Corregido y verificado** en las capas enfocadas, de lint, de tipos y de eval.
C3 (lector de pantalla) y H2 (`app.py < 2 300`) siguen **no verificados / no
incumplidos**: no son defectos y abren contrato nuevo.

Los otros `promptfooconfig*.yaml` (extendido, funcional, funcional_t05 y
conversacional) se ejecutaron el 2026-11-17 con `promptfoo@0.125.1`
(`--max-concurrency 1 --no-cache`), todos al **100 %**:

| Config | Resultado |
|---|---|
| `promptfooconfig_extendido.yaml` | 14/14 |
| `promptfooconfig_funcional.yaml` | 9/9 |
| `promptfooconfig_funcional_t05.yaml` | 9/9 |
| `promptfooconfig_conversacional.yaml` | 7/7 |

Se corrieron con `TUKUL_EVAL_MODEL=deepseek-ai/DeepSeek-V4-Flash` porque el
alias `-0731` devolvía `HTTP 429 engine_overloaded` («Model busy, retry later»)
en el momento de la ejecución; el alias sin sufijo respondió `HTTP 200` con la
misma credencial. No es un defecto del código ni de la key: el identificador por
defecto sigue siendo `-0731` y basta exportar la variable para volver a él.
