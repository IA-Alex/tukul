# Corte de `0.8.4` — correcciones de la auditoría conector del 2026-11-18

> **Disposición posterior:** este candidato no llegó a publicarse como `v0.8.4`;
> las funciones nuevas añadidas después abrieron el contrato `0.9.0` en
> [contratos-0.9.md](../contracts/contratos-0.9.md). El pendiente de evals
> registrado aquí sigue siendo requisito heredado del contrato 0.8.

Sesión del 2026-11-18. Skills: `connector-fullstack-audit` (auditoría) +
`reparador-integral-es` (reparación). Sucede a
[`cierre-0.8.3.md`](cierre-0.8.3.md).

## Por qué un parche y no contrato nuevo

Los hallazgos DF-001 y DF-005 son **defectos confirmados** según
[`POLITICA_CONGELACION.md`](../POLITICA_CONGELACION.md): el comportamiento
observable no cumplía lo prometido.

- **DF-001:** el orquestador unía los hilos con `join(timeout=45)` sin distinguir
  «terminó» de «seguía vivo»; una fuente lenta desaparecía sin error registrado,
  contra el contrato de degradación granular que promete un error por fuente.
- **DF-005:** `_stix_stream._encontrar_inicio_lista` buscaba la primera aparición
  literal de `"objects"`; un bundle con una clave anidada antes que la raíz
  hacía leer la lista equivocada, aunque el contrato del parser es leer los
  objetos del bundle.

DF-002 (docstrings «cinco fuentes») y DF-003 (`_read_bounded` muerto) son
correcciones menores de la misma pasada. Ninguno abre capacidad nueva, así que
van en parche `0.8.4`, no en contrato nuevo.

## Contenido del corte

Cuatro commits de corrección sobre `0.8.3` (más el commit de documentación que
añade este acta y sube la versión):

| Commit | Cambio | Tipo |
|---|---|---|
| `a9d98b8` | Orquestador registra el timeout de cada fuente; parser STIX anclado a la raíz; retira `_read_bounded`; docstrings | Defecto confirmado (DF-001, DF-005) + menor (DF-002, DF-003) |
| `057046f` | Adaptador de eval: reintenta la saturación (429/5xx) y explica el 401/403; retira un `noqa` inerte (RUF100) | Defecto confirmado |
| `02eddab` | Informe `auditoria-conector-2026-11-18.md` (`DF-001..DF-005`); ADR-0003 (filtro MITRE intencional); CHANGELOG | Documentación |
| `2c8f89f` | ADR-0006: reconciliación de la numeración de hallazgos (`DF-NNN` vs la serie histórica `H-NN`) | Documentación |

Evidencia detallada: [`auditoria-conector-2026-11-18.md`](auditoria-conector-2026-11-18.md).

## Verificación

### Gate local (`./scripts/quality-gate.sh`)

`✓ QUALITY GATE PASSED` (EXIT=0) — **912 passed**, 0 omitidas, cobertura total
**87,38 %**. `ruff` y `mypy` limpios; instalación aislada, `--health`,
`pip-audit` y `bandit` en verde.

### Evals promptfoo

**No verificados.** Los tres `promptfooconfig*.yaml` requieren red y credencial.
La credencial del `.env` (`DEEPINFRA_API_KEY`) sigue respondiendo **HTTP 401**
contra el endpoint (comprobado con una llamada directa en esta sesión, igual que
en el cierre de `0.8.3`). No es un defecto del arnés ni del cambio de esta
versión: es una credencial caducada. Queda como verificación **pendiente**, no
como verde, según `RELEASE.md` («si el entorno no tiene red, el paso no es
verificable: se registra como tal, no se declara verde»).

### Coherencia de versión

`pyproject.toml` = `uv.lock` = `--health` = **`0.8.4`**; `uv lock --check` limpio.

## Estado del dictamen

**Preparado, pendiente de tag.** El corte está listo en local (código, tests,
docs, versión y CHANGELOG coherentes; gate verde). El tag `v0.8.4` y su Release
firmado en CI quedan **sin crear en esta sesión**, a la espera de: (a) una
credencial válida para correr los evals, y (b) autorización explícita para
publicar.

Deuda viva no bloqueante (heredada de `0.8.3`):

- **Evals** — sin credencial válida (401).
- **C3** — límite de plataforma de Tk (ver `verificacion-c3-atspi-2026-11-17.md`).
- **H2** (`app.py < 2 300`) — no-defecto declarado (ADR-0005).
