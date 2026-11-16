# Reparación — evals de Tukul `0.8.0`

**Fecha:** 2026-11-16 · **Skills:** `reparador-integral-es`, `backend-quality-elite`
**Área:** `evals/` contra `HEAD 6977027` (`v0.7.2-5`).
**Sustituye a:** `diagnostico-evals-2026-11-16.md` (diagnóstico provisional, con
una hipótesis que la reprobación descartó; se conserva como registro).

---

## Causa raíz

**El eval no distinguía una revisión vacía de una respuesta fuera del contrato,
así que el resultado de un caso dependía de qué forma devolviera el modelo.**

**Evidencia:**

| Ejecución | Resultado |
|---|---|
| Promptfoo, sin key exportada | 0/8 — HTTP 401 (fallo de entorno) |
| Promptfoo, key exportada, `--no-cache` | 7/8 — el caso de ortografía falló |
| Misma llamada fuera de Promptfoo (3×) | 3/3 `ok` — el adaptador no perdía nada |
| Promptfoo, 5 pasadas seguidas | 8/8 en las cinco |
| `diagnose_findings('{"review":"x"}')` | `esquema_ajeno` |
| `diagnose_findings('{"findings":[]}')` | `sin_hallazgos` |
| Aserción del caso «artículo limpio» | solo `contrato_json.js`, que acepta una negativa o `sin_hallazgos`: **una respuesta `{"review":…}` pasaba como «limpio»** |

El fallo del 2026-11-16 no era el parser ni el prompt: era que el caso
«artículo limpio» **premiaba** que el modelo no entregase el contrato. Un
`{"review": …}` no es sospechoso de nada para `contrato_json.js`, porque esa
aserción existe para tolerar negativas ante inyección.

**Corrección de un diagnóstico previo:** había clasificado el fallo como
«flakiness pura del modelo». Falso. La variabilidad del modelo es real, pero no
era la causa del falso verde: el caso era **incapaz de fallar** por esa vía.

## Baseline (antes de editar)

| Comando | Resultado |
|---|---|
| `xvfb-run -a pytest tests/test_contrato_revision.py tests/test_prompts_por_modo.py` | 27 pasadas |
| `ruff check evals/` · `mypy evals/proveedor_tukul.py` | limpios |
| `uv lock --check` | limpio |
| Gate completo (versión anterior de `evals/`) | 858 pasadas, 0 omitidas, 87,77 % |

## Tabla de impacto

| Componente | Relación | ¿Cambio? | Motivo |
|---|---|---|---|
| `evals/proveedor_tukul.py` | produce la salida del eval | **Sí** | Publica `review_shape`: el parser colapsa a propósito; el eval necesita el matiz |
| `evals/asserts/revision_entregada.js` | consume `review_shape` | **Sí (nuevo)** | Cierra el falso verde en el caso de artículo limpio |
| `evals/promptfooconfig.yaml` | configuración del caso | **Sí (1 aserción)** | Añade la aserción al caso «artículo limpio» |
| `evals/asserts/contrato_json.js` | tolerancia a negativas | No | Correcta para casos de inyección; no se toca |
| `evals/promptfooconfig_extendido.yaml`, `_conversacional.yaml` | otros evals | No | No tienen caso de artículo limpio con paciente falsa |
| `tukul_core/review.py`, `tukul_core/prompts.py` | producto | **No** | El producto está bien: el parser conserva su contrato |
| `tests/test_adaptador_eval.py` | prueba de regresión | **Sí (nuevo)** | Fija en ambos sentidos la clasificación de forma |

## Cambios

1. `evals/proveedor_tukul.py` — `_forma_de_revision()` y `metadata.review_shape`
   (`findings` / `vacia` / `otra` / `prosa`). No reinterpreta el contrato: llama
   a `diagnose_findings` y añade el matiz que `sin_hallazgos` no puede dar.
2. `evals/asserts/revision_entregada.js` — acepta `vacia` y `findings`; rechaza
   `otra` y `prosa`. Sin `review_shape` falla cerrado.
3. `evals/promptfooconfig.yaml` — segunda aserción en «Un artículo limpio no
   rompe el contrato».
4. `tests/test_adaptador_eval.py` — 7 pruebas: cinco sobre la clasificación,
   una de regresión y una de fallo legible sin key.

## Verificaciones

| Verificación | Comando | Resultado |
|---|---|---|
| Aserción en ambos sentidos | `node` sobre `revision_entregada.js` con las 4 formas | 6/6 correctas |
| Área enfocada | `pytest tests/test_adaptador_eval.py tests/test_contrato_revision.py tests/test_prompts_por_modo.py` | **34 pasadas** |
| Lint/tipos | `ruff check` · `mypy evals/proveedor_tukul.py` | limpios |
| Eval base | `promptfoo -c evals/promptfooconfig.yaml --no-cache` | **8/8**, caso limpio `review_shape=vacia` |
| Eval ampliado | `-c evals/promptfooconfig_extendido.yaml` | **14/14** |
| Eval conversacional | `-c evals/promptfooconfig_conversacional.yaml` | **7/7** |
| Gate completo | `xvfb-run -a ./scripts/quality-gate.sh` | ver «Estado» |
| Tag `v0.8.0` | `git describe --tags` | **no creado**: requiere confirmación explícita |

## Estado

**Parcial, a la espera del gate.** La reparación está aplicada y verificada en
las capas enfocadas, de lint y de eval; falta el resultado del gate completo y
la creación del tag, que es una acción externa que se pide aparte.

## Riesgos residuales

- El modelo sigue siendo no determinista. Ahora la mayoría de sus desviaciones
  **cuentan como fallo** (que es lo deseado) en lugar de pasar como acierto.
- La rama `otra` rechaza también un `{"findings": …}` válido; no lo hace: esa
  forma la clasifica `findings` antes de llegar.
