# Corte de `0.8.1` — cierre del contrato `0.8.0`

Sesión del 2026-11-16. Skills: `arquitecto-asesor` (lectura) + `reparador-integral-es`
(reparación) + `finishing-a-development-branch` (cierre de rama).
Sucede al contrato [`contratos-0.8.md`](../contracts/contratos-0.8.md) (F5/F6).

## Por qué `0.8.1` y no reescribir `0.8.0`

`v0.8.0` se publicó el 2026-11-17 (commit `d6c4788`) con su Release. Al revisar
el cierre se encontró que esa versión arrastraba dos defectos confirmados:

1. **H-1 (crítico):** el prompt por modo de F5 quedó **sin cablear** en la
   interfaz. `RequestLifecycle` recibía `request_type="review"` pero nunca lo
   traducía a `modo`, así que `stream_response` caía en su default
   («conversacion») y la revisión enviaba el prompt de chat, sin el contrato
   JSON. Es un **defecto confirmado**: el comportamiento observable no cumplía
   lo prometido por el contrato. La suite no lo veía porque todos los tests
   miraban al cliente (`LLMClient`), no la ruta de la app.
2. **Fallo de entrega:** `tests/test_evals_asercciones.py` invocaba
   `.venv/bin/python` por ruta relativa; en GitHub Actions no hay `.venv` y el
   job `test` caía en 3.11, 3.12 y 3.13 (runs `44024398058`, `44021149550`).

Como `v0.8.0` **ya estaba publicado**, la política
([`POLITICA_CONGELACION.md`](../POLITICA_CONGELACION.md)) prohíbe reescribir el
tag. Se publica un parche `0.8.1`, que no añade capacidades.

## Correcciones y su evidencia

| Hallazgo | Severidad | Corrección | Evidencia en ambas direcciones |
|---|---|---|---|
| **H-1** revisión con prompt de chat | Crítica | `app.py` pasa `modo="revision"`/`"conversacion"`; `RequestLifecycle.start` acepta y reenvía `modo` | `test_revisar_envia_el_modo_revision` falla sin el fix (`None != 'revision'`) y pasa con él; `test_request_lifecycle.py::TestModoDelPrompt` en ambos flujos |
| **CI** test con ruta `.venv` | Alta | `sys.executable` en vez de la ruta del venv (mismo patrón que el resto de `tests/`) | Los tres jobs `test` pasan en CI con la corrección |

## Verificación

### Gate local (`./scripts/quality-gate.sh`)

`✓ QUALITY GATE PASSED` — **888 passed**, 922 registradas, **0 omitidas**,
cobertura total **87,75 %** (mínimo 70 %). `ruff` y `mypy` limpios (69 archivos),
instalación aislada, `--health`, `--config`, CLI, `pip-audit` y `bandit` verdes.

### Coherencia de versión

`pyproject.toml` = `uv.lock` = `--health` = **`0.8.1`**. `uv lock --check` limpio.

### CI del commit tageado (`ba36b79`, run `44026728270`)

**success** en `test (3.11)`, `test (3.12)`, `test (3.13)` y `security`. Primera
vez verde desde `v0.7.2`.

### Release y verificación en destino

Release `v0.8.1` (run `44026732036`, success): no draft, no prerelease, con
`tukul-linux-x86_64` (34 961 024 B), `SHA256SUMS`, `sbom.cdx.json` y
`tukul-linux-x86_64.bundle`. Verificado **sobre lo descargado** con
`gh release download`, no sobre lo construido:

- `sha256sum -c SHA256SUMS` → **«La suma coincide»**.
- `./tukul-linux-x86_64 --health` → **`versión: Tukul 0.8.1`**, exit 0.
- `cosign verify-blob` → **No ejecutado: `cosign` no está instalado en esta
  máquina**. La firma keyless se verifica dentro del propio workflow
  (`build-release.yml`, run success) y el bundle es un sigstore bundle v0.3
  bien formado; la verificación independiente queda pendiente de un host con
  `cosign`.

## Deuda viva (no bloqueante de este contrato)

- **H-4 (P1):** el adaptador del eval (`evals/proveedor_tukul.py:45`) importa
  `SYSTEM_PROMPT` (= prompt de revisión, fijo), así que **no** prueba el
  cableado del modo. Debe importar de `tukul_core.prompts` y cubrir la ruta por
  modo. Abre corrección futura.
- **H-5 (P1):** `ui_state._ajustar_al_presupuesto_global` reutiliza `_abreviar`,
  que mide el exceso contra la cuota **por documento**; cuando el mapa excede el
  tope global descarta turnos enteros en vez de abreviarlos (reproducido: 20
  turnos → 17, 0 marcas de recorte), en contra de su docstring y del CHANGELOG.
- **Evidencia de evals:** los tres `promptfooconfig*.yaml` no se pudieron
  ejecutar en esta sesión. `promptfoo` no está instalado (se fija `0.125.1` en
  `evals/README.md` para reproducibilidad) y la credencial `DEEPINFRA_API_KEY`
  del `.env` responde **HTTP 401** contra el endpoint. No es un fallo del
  arnés: es una credencial caducada. Queda como verificación pendiente.
- **C3 — lector de pantalla:** sin host con Orca; no verificado.
- **H2 — `app.py < 2 300`:** 2 647 líneas; declarado no-defecto (ADR-0005).

## Estado del dictamen

**CERRADO para `0.8.1` en lo verificable.** Las capacidades F5/F6 están
implementadas y **cableadas** (H-1 corregido y fijado por regresión), el CI es
verde, la coherencia de versión y el artefacto están demostrados sobre lo
descargado. La firma se verificó en CI, no en este host (falta `cosign`). La
deuda H-4/H-5 y la ejecución de los evals abren contrato posterior: no
reabren `0.8.1`, que solo corrige defectos confirmados.
