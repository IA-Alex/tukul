# Reparación integral 2026-11-12 — hallazgos, residuos y pendientes

Baseline (§0) registrado antes de editar: ruff producto limpio, mypy limpio,
687 tests OK, cobertura 88 %.

## Trabajo

- [x] **R1** Residuo: estilo ttk muerto `PanelTitulo.TLabel` eliminado (`tema.py`).
- [x] **Q1** `--health` reporta versión y commit (`tukul_core/version.py`).
- [x] **Q2** `CONTRIBUTING.md` + política de versionado/flujo de ramas; enlazado
      desde `README.md` y `docs/README.md`.
- [x] **S1** `tests/test_auditoria_regresion.py` (1.544 líneas) dividido por
      dominio en 6 archivos + `tests/_regresion_helpers.py`. Mismas 69 pruebas.
- [x] **P1** Equivalencia de lockfiles: `uv.lock` estaba **obsoleto** (`tukul`
      0.3.2, sin `pytest-timeout` ni `locust`; versiones divergentes). Se
      regeneró con `uv lock --upgrade` y `requirements-dev.lock` con `uv export`
      (derivado de `uv.lock` por construcción). Test de regresión:
      `tests/test_lockfiles_equivalentes.py`.
- [ ] **H2** Extraer bloques de `app.py` para bajar de 2.300 líneas.
      **No iniciado.** Requiere refactor mecánico de gran superficie (métodos
      `_build_*` y clúster de apariencia) con reescritura de `self.`→`app.`;
      se dejó para una tarea dedicada tras revisar el diff con el usuario.

## Verificación (§6)

- `ruff check tukul_core tukul_ui tukul.py tests` → limpio.
- `mypy tukul_core tukul_ui tukul.py` → limpio (58 módulos).
- `pytest --cov` → **690 pruebas, 87.6 %**, sin omisiones.
- Herramientas verificadas con las versiones del lock regenerado
  (ruff 0.17.5, mypy 2.4.1) instaladas desde `requirements-dev.lock`.

## No verificado / pendiente

- H2 (refactor de `app.py`): fuera de esta pasada.
- H0 (CI sin runners): bloqueo de cuenta, no de código.
- Windows real y accesibilidad AT-SPI: sin entorno aquí.
