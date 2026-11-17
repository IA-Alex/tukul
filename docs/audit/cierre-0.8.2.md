# Corte de `0.8.2` — cierre de la deuda P1 de `0.8.1`

Sesión del 2026-11-16. Skills: `reparador-integral-es` (reparación) +
`arquitecto-asesor` (lectura) + `finishing-a-development-branch` (cierre).
Sucede a [`cierre-0.8.1.md`](cierre-0.8.1.md), que dejó abierta la deuda P1
(H-4 y H-5) al cerrar el contrato `0.8.0`.

## Por qué un parche y no contrato nuevo

Ambos hallazgos son **defectos confirmados** según
[`POLITICA_CONGELACION.md`](../POLITICA_CONGELACION.md): el comportamiento
observable no cumplía lo ya prometido.

- **H-5:** el docstring de `persistir_conversacion` y el CHANGELOG prometen que
  el recorte «abrevia, nunca descarta un turno por completo»; la poda global
  descartaba turnos enteros sin marca.
- **H-4:** el README de evals afirma que mide «lo que la aplicación envía de
  verdad»; el adaptador usaba un prompt de revisión fijo y no podía medir otro
  modo.

No encajan en ninguna categoría de función nueva, así que abren parche
`0.8.2`, no contrato nuevo.

## Causa raíz y corrección

| Hallazgo | Causa raíz (evidencia) | Corrección |
|---|---|---|
| **H-5** | `_abreviar` medía el exceso contra la cuota **por documento** (`ui_state.py:189`), así que en la poda global —donde cada documento ya cabe en su cuota— devolvía `False` y el bucle ejecutaba `turnos.pop(0)` (línea 162) | `_abreviar` recibe el `exceso` a liberar; cada llamador lo mide en su ámbito (documento o mapa). El mensaje se recorta hasta el mínimo antes de permitir un descarte |
| **H-4** | El adaptador importaba el re-export fijo `SYSTEM_PROMPT` (= `prompt_sistema("revision")`, `llm.py:24`) y lo usaba siempre (`proveedor_tukul.py:45,218`) | Usa `prompt_sistema(modo)`, con modo por defecto `revision` y configurable con `vars.mode`; publica `prompt_mode` en la metadata |

## Reproducción (H-5)

Antes: 10 documentos de 20 turnos cada uno → **17 turnos, 0 marcas de recorte**
(se descartaban, no se abreviaban). Después: **20 turnos, 3 mensajes abreviados
con marca**. La prueba `test_la_poda_global_abrevia_y_no_descarta_turnos` falla
con el código previo (`17 != 20`) y pasa con la corrección.

## Tabla de impacto

| Componente | Relación | ¿Cambió? | Motivo |
|---|---|---|---|
| `tukul_ui/ui_state.py` | produce el recorte | **Sí** | H-5: exceso como parámetro |
| `evals/proveedor_tukul.py` | produce la salida del eval | **Sí** | H-4: resuelve por modo |
| `evals/README.md` | documenta fidelidad | **Sí** | H-4: la afirmación era falsa para otros modos |
| `tests/test_ui_state.py`, `tests/test_adaptador_eval.py` | prueba | **Sí** | Regresiones de H-5 y H-4 |
| `tukul_core/prompts.py`, `llm.py` | provee `prompt_sistema` | **No** | Ya correctos |
| `tukul_ui/app.py` | productor del modo | **No** | Corregido en H-1 (`0.8.1`) |
| `evals/promptfooconfig*.yaml` | configuración | **No** | Los evals siguen siendo de revisión; `vars.mode` es opcional |

## Verificación

### Gate local (`./scripts/quality-gate.sh`)

`✓ QUALITY GATE PASSED` — **892 passed**, 926 registradas, **0 omitidas**,
cobertura total **87,65 %**. `ruff` y `mypy` limpios (70 archivos), instalación
aislada, `--health`, pip-audit y bandit verdes.

### Regresiones en ambas direcciones

- H-5: `test_la_poda_global_abrevia_y_no_descarta_turnos` → FAIL con el código
  previo (`17 != 20`), PASS con la corrección.
- H-4: `TestModoDelPrompt` (3 pruebas) → FAIL con el adaptador previo
  (`AttributeError: prompt_sistema`), PASS con la corrección.

### Coherencia de versión

`pyproject.toml` = `uv.lock` = `--health` = **`0.8.2`**. `uv lock --check` limpio.

### Estado del dictamen

**CERRADO en lo verificable.** La deuda P1 del corte anterior (H-4, H-5) está
corregida y fijada por regresión. Sigue como deuda no bloqueante la ejecución
de los evals (credencial 401), C3 (lector de pantalla) y H2 (`app.py < 2 300`),
que abren contrato posterior.
