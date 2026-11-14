# SDD ledger — plan: docs/audit/_plan-frontend-2026-11-13.md (ADR-0005 pasos 2 y 3)

Plan: ADR-0005 (docs/decisions/ADR-0005-god-object-extraction.md), pasos 2 y 3.
Spec/authority: auditoría `docs/audit/auditoria-frontend-2026-11-13.md` (DF-001).

## Baseline
- ruff: All checks passed.
- mypy: Success, 66 source files.
- HEAD: 4ffbeae (working tree limpio).
- tests/test_app_ramas.py: TestPipelineDeIdeas falla/hang en HEAD sin cambios
  (MagicMock 'after' _mock_check_sig timeout). Preexistente, no introducido aquí.

## Tarea 1 (paso 2 ADR-0005): ventana/DPI/geometría/tema → window_shell.py
- Creado `tukul_ui/window_shell.py` (`WindowShell`): dueño de `theme` y del
  acceso a Tk para DPI, tamaño inicial, geometría y tema. Saneado puro sigue en
  `tukul_ui.ventana` (reexpuesto).
- `TukulApp` conserva delegaciones (`_ajustar_dpi`, `_aplicar_tamano_inicial`,
  `_ventana_mapeada`, `_restaurar_geometria`, `_theme`, `_tema_validado`,
  `PATRON_GEOMETRIA`, saneadores) para no romper consumidores ni tests.
- Nuevo `tests/test_window_shell.py` (15 tests). `TukulApp._geometria_saneada_actual`
  mantiene el punto de parcheo de `_ventana_mapeada` (política de persistencia en
  el host, medición en el shell).
- Ruling: `TestTamanoInicial` (test_app_ramas) reapuntado a `WindowShell` con host
  registrador — el comportamiento es idéntico y el test original ejercía la lógica
  ahora extraída con `TukulApp.__new__` (sin `_shell`). Coste si me equivoco: bajo
  (la misma aserción sigue viva en test_window_shell.py).
- Verificación: ruff limpio; mypy limpio (67 ficheros); test_window_shell 15/15,
  test_tema 25/25, test_estado_ui 28/28, subconjunto test_app_ramas verde.
- app.py: 2658 → 2611 líneas.

Task 1: complete (tests: pytest tests/test_window_shell.py tests/test_tema.py tests/test_estado_ui.py → 68 passed en verde tras fix)
