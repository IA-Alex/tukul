# Contrato de cierre — Tukul `0.7.0` (ciclo nuevo)

Estado: **abierto (en corte)** — el contrato rige la entrega de `0.7.0`.
Base del dictamen: `docs/audit/_plan-cierre-0.7.0.md` (ruta A) y
`docs/audit/auditoria-frontend-2026-11-13.md` (DF-001…DF-016).
Sucede a `docs/contracts/contratos-0.6.md`, cerrado en `0.6.0` con parche
`0.6.1`.

## Por qué contrato nuevo y no parche `0.6.x`

La política de congelación de `0.6.0` solo acepta correcciones con evidencia de
defecto, promesa incumplida y prueba que falla antes y pasa después. `0.7.0`
incorpora **funciones nuevas y refactorizaciones** (autoindexado, fuentes de IA,
extracción de `TukulApp`), que no encajan en ninguna de las cuatro categorías de
corrección. Un contrato nuevo es la vía correcta, no una excepción.

El corte se hace sobre un HEAD que contiene el código declarado, de modo que
código, artefacto distribuido y versión ejecutada coincidan: el fallo que motivó
la reapertura (**tag ≠ HEAD**, 17 commits sin release) se cierra cortando
`v0.7.0` sobre este mismo commit.

## Capacidades esenciales comprometidas

Cada una con su criterio de aceptación verificable.

### F1 — Fuentes de IA en el pipeline de ideas

- **Capacidad:** el análisis de correlaciones puede incluir publicaciones de IA
  desde **OpenAlex** y **HuggingFace Papers**, con degradación por fuente (la
  caída de un proveedor no tumba el pipeline).
- **Criterio de aceptación:** los adaptadores existen y devuelven elementos
  normalizados ante respuestas válidas; ante error de red o respuesta inválida,
  la fuente se marca degradada y el pipeline continúa. Regresión en
  `tests/test_openalex_adapter.py`, `tests/test_huggingface_papers_adapter.py`
  y `tests/test_ideas_fuentes_ia.py`.
- **Fuera de alcance:** nuevas fuentes, rediseño del pipeline.

### F2 — Autoindexado del corpus al arrancar

- **Capacidad:** al abrir la ventana se indexa la carpeta de artículos en
  segundo plano, de forma incremental, sin bloquear el arranque.
- **Criterio de aceptación:** el arranque no se bloquea mientras indexa; el
  indexado es incremental (no reindexa lo ya indexado). Regresión en
  `tests/test_memoria_autoindexado.py`.

### F3 — Botón «Limpiar» en el panel del asistente

- **Capacidad:** vacía la conversación activa; se deshabilita cuando no hay nada
  que limpiar.
- **Criterio de aceptación:** con conversación, el botón invoca el callback de
  limpieza; sin conversación, queda deshabilitado. Regresión en
  `tests/test_limpiar_panel.py`.

### F4 — Icono de ventana e isotipo

- **Capacidad:** el binario embebe el isotipo (`app_icon.py`); el isotipo de la
  cabecera baja a 18 px. Sin assets externos.
- **Criterio de aceptación:** el icono de ventana se aplica sin depender de
  archivos en disco; el isotipo de cabecera mide 18 px.

## Refactorización comprometida (DF-001 / ADR-0005)

- **Capacidad:** extracción por responsabilidades de `TukulApp` sin cambiar el
  comportamiento observable. Módulos: `credentials.py`, `window_shell.py`,
  `editor_session.py`, `dialogs_base.py`.
- **Criterio de aceptación:** la suite completa sigue verde con las mismas
  pruebas de contrato; cada `patch` afectado por la extracción fue revisado (no
  solo «pasa»); `TukulApp` conserva delegaciones y *properties* de
  compatibilidad; el tema pasa a una sola fuente.
- **Nota:** el objetivo métrico `app.py < 2 300` (H2) **no** se alcanza con las
  delegaciones (`app.py` ≈ 2 622 líneas). Se cierra **por responsabilidades** y
  la métrica se reevalúa al retirar los *shims* (ver ADR-0005). No es defecto.

## Correcciones incluidas (DF-002…DF-016)

- **DF-002** (Alto): guardas de cierre en cada `after(0, …)` desde workers vía
  el helper `publicar_en_hilo_ui` (`worker_threads.py`).
- **DF-003** (Alto): `add_references` avisa cuando descarta todos los archivos.
- **DF-004…DF-016** (Medio/Bajo): base única de diálogos, presupuesto único,
  mensaje de memoria unificado, «Probar conexión…» con estado, retirada de
  métodos fachada, tooltip con recorte vertical, tope de retención del
  historial, nombres accesibles. Detalle en
  `docs/audit/auditoria-frontend-2026-11-13.md`.

## Criterios de aceptación transversales (DoD de entrega)

1. **Gate único verde:** `./scripts/quality-gate.sh` termina en
   `✓ QUALITY GATE PASSED`, con 0 pruebas omitidas y cobertura ≥ 70 %.
2. **Coherencia de versión:** `pyproject.toml`, `uv.lock` y `--health` reportan
   `0.7.0`. `uv lock --check` limpio.
3. **Correspondencia código ↔ artefacto ↔ versión:** el tag anotado `v0.7.0` se
   corta sobre el HEAD validado; `git describe --tags` → `v0.7.0` limpio.
4. **Documentación alineada:** CHANGELOG `[0.7.0]`, este contrato y
   `docs/POLITICA_CONGELACION.md` describen el mismo estado.

## Riesgos residuales (no bloqueantes, no verificados)

- **C3 — accesibilidad con lector de pantalla:** sin host con Orca. Queda
  *Experimental*, limitación declarada (contraste, foco y foco devuelto
  verificados; lector de pantalla **no verificado**). Abre contrato futuro, no
  bloquea `0.7.0`.
- **C4 — sostenibilidad de proveedores:** sin umbral decidido. Queda
  *descriptivo*. No bloquea `0.7.0`.
- **H2 — `app.py < 2 300`:** no alcanzado; mejora métrica reevaluable, no
  requisito de este contrato.

## Reglas que no se negocian

- **Nunca se reescribe un tag publicado.** `v0.6.0` y `v0.6.1` quedan como
  están.
- **Sin `|| true` en firma ni verificación.**
- El gate se ejecuta antes de cortar el tag; un gate rojo detiene la
  publicación.
