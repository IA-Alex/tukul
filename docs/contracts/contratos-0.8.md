# Contrato de cierre — Tukul `0.8.0` (ciclo nuevo)

Estado: **abierto**.
Sucede a `docs/contracts/contratos-0.7.md`, cerrado en `0.7.2`.
Base: `docs/audit/redteam-2026-11-15.md` (hallazgo L2) y la observación de
incoherencia funcional registrada en `docs/audit/cierre-0.7.1.md`.

## Por qué contrato nuevo y no parche `0.7.x`

`0.7.x` solo admite correcciones con defecto confirmado, promesa incumplida y
prueba que falla antes y pasa después. Este ciclo **cambia el diseño del
prompt de sistema** (de uno único a uno por modo), que no encaja en ninguna de
las cuatro categorías: no hay una promesa incumplida —la app hace lo que dice—
sino un comportamiento que no es coherente con su naturaleza.

Un contrato nuevo es la vía correcta, no una excepción.

## Evidencia del problema

El `SYSTEM_PROMPT` es único para tres tareas con requisitos distintos. El
contrato de revisión ocupa el 60 % de su texto y contamina los otros modos:

| Modo | Qué necesita | Qué recibe hoy |
|---|---|---|
| **Conversación** | Hablar del artículo; responder preguntas | Instrucciones de «devuelve el contrato JSON de la revisión» y «reporta SIEMPRE los hallazgos» |
| **Revisión** | Contrato JSON estricto, no inventar | Correcto |
| **Enriquecimiento de ideas** | Mejorar una idea en JSON | El contrato de revisión, que no aplica |

**Síntoma medido (2026-11-15):** al preguntar «¿qué es Tukul?» en modo
conversación, el modelo respondió describiendo su propio rol de guardián en
lugar de conversar sobre el artículo. No hubo filtración literal, pero sí
divulgación de la misión del sistema.

## Capacidades esenciales comprometidas

### F5 — Prompt de sistema por modo

- **Capacidad:** cada modo (conversación, revisión, enriquecimiento de ideas)
  envía un prompt de sistema propio, adecuado a su tarea. La defensa común
  (texto no confiable, no revelar instrucciones, no cambiar de rol) se
  comparte, no se duplica.
- **Criterio de aceptación:**
  - Existe `tukul_core/prompts.py` con una base común y tres prompts por modo.
  - `LLMClient.complete` y el cliente de streaming aceptan el modo y envían el
    prompt correspondiente.
  - El prompt de revisión conserva **íntegras** las reglas de contrato JSON,
    `omitted` y «reporta SIEMPRE»: los 14 casos del eval ampliado y los 8 de
    línea base siguen pasando.
  - El prompt de conversación **no** contiene la instrucción de devolver el
    contrato JSON de revisión.
  - Regresión en `tests/test_prompts_por_modo.py`.

### F6 — Defensa común compartida y verificada

- **Capacidad:** las reglas antisoborno (dato no confiable, marcas de sistema
  falsas, no revelar instrucciones, no cambiar de rol) están en la base común,
  así que ningún modo queda sin ellas.
- **Criterio de aceptación:** el prompt de cada modo contiene la base común;
  un test recorre los tres modos y comprueba que cada uno conserva la defensa.
  La batería de inyección (eval ampliado) sigue en verde tras el cambio.

## Correcciones incluidas

Ninguna. Este ciclo solo añade F5 y F6.

## Criterios de aceptación transversales (DoD de entrega)

1. **Gate único verde:** `./scripts/quality-gate.sh` termina en
   `✓ QUALITY GATE PASSED`, con 0 pruebas omitidas y cobertura ≥ 70 %.
2. **Coherencia de versión:** `pyproject.toml`, `uv.lock` y `--health` reportan
   `0.8.0`. `uv lock --check` limpio.
3. **Correspondencia código ↔ artefacto ↔ versión:** tag anotado `v0.8.0`
   sobre el HEAD validado; `git describe --tags` → `v0.8.0` limpio.
4. **Documentación alineada:** CHANGELOG `[0.8.0]`, este contrato y
   `docs/POLITICA_CONGELACION.md` describen el mismo estado.
5. **Evals verdes:** `promptfooconfig.yaml`, `promptfooconfig_extendido.yaml` y
   `promptfooconfig_conversacional.yaml` al 100 %, con las aserciones ya
   corregidas en `0.7.2`.

## Riesgos residuales (no bloqueantes)

- **C3 — accesibilidad con lector de pantalla:** sin host con Orca. Sigue
  *Experimental*, no bloqueante.
- **C4 — sostenibilidad de proveedores:** descriptivo, sin umbral.
- **H2 — `app.py < 2 300`:** sigue reevaluable al retirar los *shims*.
- **Divergencia con el modo real del modelo:** el prompt de conversación pide
  una respuesta libre; un modelo puede ignorar el tono pedido. Se mide con el
  eval conversacional, no se garantiza.

## Reglas que no se negocian

- **Nunca se reescribe un tag publicado.** `v0.7.0`, `v0.7.1` y `v0.7.2`
  quedan como están.
- **Sin `|| true` en firma ni verificación.**
- El gate se ejecuta antes de cortar el tag; un gate rojo detiene la
  publicación.
- **La defensa no se debilita para ganar naturalidad:** si la separación por
  modo rompe la resistencia a inyección, el cambio no entra.
