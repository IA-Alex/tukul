# Plan de cierre — Tukul 0.7.0 (contrato nuevo)

Ruta elegida: **A — publicar 0.7.0 con contrato nuevo**. Resuelve H1/H2/H3 de la
auditoría de cierre de esta sesión.

## Pasos

1. [x] Quality gate local verde (`./scripts/quality-gate.sh`), 0 omitidas, cov ≥70 %.
2. [x] Subir versión a `0.7.0` (`pyproject.toml`).
3. [x] Entrada `[0.7.0]` en `CHANGELOG.md` (features + refactors + fixes).
4. [x] Contrato del ciclo `docs/contracts/contratos-0.7.md`.
5. [x] Actualizar `docs/POLITICA_CONGELACION.md` al estado real (`0.7.0`).
6. [x] Verificar coherencia docs ↔ código (ARCHITECTURE, contratos).
7. [x] Commit + tag `v0.7.0` (push/Release = acción externa: pedir antes).

## Evidencia registrada

- **Gate:** `./scripts/quality-gate.sh` → `✓ QUALITY GATE PASSED`,
  **827 passed, 0 failed**, 852 pruebas registradas, **0 omitidas**,
  cobertura **87.59 %**. ruff/mypy/instalación aislada/lockfile con
  hashes/`--health`/`--config`/CLI/pip-audit/bandit verdes.
- **Defecto corregido:** `uv.lock` fijaba `0.6.1` (fallaba
  `tests/test_lockfiles_equivalentes.py::test_uv_lock_fija_la_version_del_proyecto`).
  Regenerado con `uv lock` → `0.7.0`; `uv lock --check` limpio.
- **Coherencia de versión:** `pyproject.toml` = `uv.lock` = `--health` = `0.7.0`.
- **`git describe --tags`** → `v0.7.0` limpio (HEAD == tag, commit `e13efd6`).
- **Commit de cierre:** `e13efd6 chore(release): cierra 0.7.0`.
- **Pendiente externo:** push de `master` + tag y Release firmada (requiere
  confirmación del mantenedor).
