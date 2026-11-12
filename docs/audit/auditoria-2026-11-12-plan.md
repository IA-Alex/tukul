# Plan — Auditoría desktop + diseño 2026-11-12

Skills: `auditor-frontend-desktop-elite` (Completa) + `frontend-design-pro`.
Modo autorizado por el usuario: auditar **y aplicar correcciones**.

> **Estado: completada.** Informe en `docs/audit/auditoria-2026-11-12.md`.
> 6 hallazgos confirmados y reparados; 10 pruebas nuevas; ruff/mypy limpios;
> 687 pruebas OK, cobertura 87.7 %. Versión 0.4.1.

## Fase 0 — Reconocimiento
- [x] Stack: Python 3.11+ / Tkinter+ttk, X11 en Linux, Windows x86_64. Standalone PyInstaller.
- [ ] Procesos, superficies privilegiadas, IPC (colas/threads), almacenamiento, red.
- [ ] Mapa de módulos UI (`app.py` 2580 líneas, dialogs, components/).

## Fase 1 — Evaluación (11 dimensiones)
- [ ] 1 Arquitectura
- [ ] 2 Seguridad (keyring, red, rutas, subprocess, deep links, updater)
- [ ] 3 Concurrencia/estado
- [ ] 4 Recursos/rendimiento
- [ ] 5 UX/accesibilidad (Tkinter a11y es débil por diseño)
- [ ] 6 Persistencia
- [ ] 7 Distribución
- [ ] 8 Compatibilidad
- [ ] 9 Calidad/pruebas
- [ ] 10 Cadena de suministro
- [ ] 11 Resiliencia

## Fase 2 — Refutación
## Fase 3 — Clasificación (DF-NNN)
## Fase 4 — Entrega + correcciones aplicadas
- [x] Informe: `docs/audit/auditoria-2026-11-12.md`
- [x] DF-001 a DF-006 aplicados y con pruebas nuevas
- [x] CHANGELOG 0.4.1 + versión en pyproject

## Resultado
- ruff limpio · mypy limpio · 687 pruebas OK · cobertura 87.7 %
- Modo: auditoría + correcciones (autorizado por el usuario)
