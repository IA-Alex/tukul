# Resultados — batería del modelo (2026-11-13)

**Modelo:** `deepseek-ai/DeepSeek-V4-Flash` vía DeepInfra.
**Parámetros:** `temperature: 0`, `seed: 7`.
**Ejecuciones:** 3 (dos decorridas con el arnés incompleto y descartadas;
la válida es `bateria-20261113T203759Z.json`).

## Resumen

| Suite | Casos | Resultado |
|---|---|---|
| `promptfooconfig.yaml` (contrato + inyección) | 8 | **8/8 PASS** |
| `promptfooconfig_conversacional.yaml` | 7 | **7/7 PASS** |
| `promptfooconfig_extendido.yaml` | 14 | **14/14 PASS** |
| **Batería D1-D3 (`scripts/bateria_modelo.py`)** | 7 | **4/7** |

Los 29 casos de promptfoo pasan. La batería nueva encuentra fallos que esos
evals no cubren: no medían **seguir instrucciones de edición**.

## Resultados de la batería

| ID | Caso | Resultado | Evidencia |
|---|---|---|---|
| I-01 | Acortar 30 % sin perder datos | **FALLA** | 962 → 476 palabras (49 %, se pasó al 30 %); perdió la entidad «Por» |
| I-03 | Reescribir solo el 2.º párrafo | **FALLA** | devolvió **1 párrafo** de 808 caracteres: truncó el artículo |
| I-06 | Instrucción contradictoria | **FALLA** | no avisó; editó igualmente |
| I-10 | Quitar muletillas | **PASS** | 10 marcadas → 0; conservó usos legítimos |
| R-01 | Artículo correcto (A-06) | **PASS** | 0 hallazgos de ortografía/gramática; sin citas inventadas |
| R-02 | 3 errores sembrados (A-07) | **PASS** | detectó **3/3**; 12 hallazgos (tope exacto) |
| F-01 | No inventar datos | **PASS** | 0 cifras y 0 fechas nuevas |

## Fallos confirmados del modelo

1. **No controla la proporción al acortar.** Pide 30 % y recorta 51 %. No es un
   problema de prompt: se le dio un objetivo numérico explícito.
2. **Trunca respuestas largas al editar.** Ante «reescribe el segundo párrafo»
   devolvió solo el primer párrafo (808 caracteres), `finish_reason: stop`.
   Confirmado con llamada directa, fuera del arnés.
3. **No detecta instrucciones imposibles.** Con «acórtalo sin quitar nada»
   editó en lugar de señalar la contradicción.

## Correcciones al arnés, no al modelo

Documentadas para no confundirlas con fallos del modelo:

- R-01/R-02 enviaban **solo el artículo**; la app envía
  `build_review_prompt()`. Con el prompt correcto, R-02 pasó de 0 a 3/3
  detecciones.
- I-01 contaba capitalizadas de inicio de frase («Por», «Esa») como entidades.
- I-03 comparaba párrafos por índice; ahora por contenido.

## Lectura para el producto

El modelo **sirve para revisar** (R-01, R-02: detecta, no inventa, respeta el
tope de 12) y **para quitar marcas de estilo** (I-10). **No sirve como editor
de instrucciones largas**: no obedece proporciones, trunca y no cuestiona
instrucciones imposibles.

Consecuencia práctica: en la UI, «Revisar artículo» es fiable; editar por
instrucción con salidas largas no lo es sin validación en la app.

## Reproducir

```bash
export DEEPINFRA_API_KEY=...
.venv/bin/python scripts/bateria_modelo.py
npx promptfoo@0.125.1 eval -c evals/promptfooconfig.yaml -j 1
```
