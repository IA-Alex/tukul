# Hallazgos abiertos de la auditoría 2026-11-04

Estado al 2026-11-10, tras la auditoría arquitectónica y su reparación.

> **Cerrados el 2026-11-10** (ver `CHANGELOG.md` 0.4.0): M4 ya estaba resuelto;
> M5 (checksums/SBOM) se implementó en `build-release.yml`; H2 sigue abierto
> (extracción de `RequestLifecycle`, refactor L). H0 se diagnosticó y se dejó
> con acción de cuenta documentada (abajo).

## H2 — `TukulApp` concentra la UI y el ciclo de petición (2.510 líneas)
- **Qué falta:** el objetivo < 2.300 sigue a ~210 líneas. Quedan bloques
  menores (`_reference_packet`, `_pedir_aprobacion`) muy acoplados al ciclo de
  petición, no extraíbles sin desdibujar ese contrato.
- **Evidencia:** `wc -l tukul_ui/app.py` → 3.150 (inicio 2026-11-10) → **2.510**
  tras mover contexto/CVE; cobertura de `app.py` 89 %.
- **Progreso (2026-11-10):** extraídos `tema.py`, `ventana.py`, `ideas.py` +
  `contexto.py` y `contexto_dialogo.py` (diálogo de contexto + fuente de
  amenazas, con la ventana inyectada). `request_lifecycle.py` y `ui_state.py`
  ya estaban.
- **Decisión tomada:** se autorizó convertir `test_hallazgos_restantes.py` de
  inspección textual a prueba de comportamiento, y reapuntar los parches de
  `test_app_ramas.py`, `test_flujo_revision.py` y `test_threat_feed_ui.py` a
  los nuevos módulos. Coherencia productor↔consumidor mantenida.
- **Cierre:** `app.py` < 2.300 líneas y cobertura del nuevo módulo ≥ 90 %.

## M4 — Contraste no textual de los bordes: RESUELTO (2026-11-04, segunda pasada)

- **Origen:** el token `borde` hacía tres trabajos a la vez (divisoria, fondo de
  hover y fondo de scrollbar) y no alcanzaba 3:1 contra ninguna capa.
- **Decisión de producto:** la paleta se rehízo a partir de la identidad del
  nombre. Tukul toma su nombre del *tunkul* maya: un tambor de percusión de
  un canuto de bambú cerrado por ambos extremos, con dos lengüetas talladas que
  emiten dos tonos (Diccionario de americanismos, ASALE). De ahí las capas de
  madera quemada y médula de caña, la fibra de bambú en los bordes y el verde
  de la lengüeta como único acento.
- **Separación de tokens:** `borde` (divisoria y hover, ahora ≥ 3:1 contra las
  tres capas) y `borde_control` (bordes de botones, campos, sash y barra de
  desplazamiento, ≥ 3:1). El hover de los botones pasa a `superficie_activa`,
  una superficie propia, para no depender del borde.
- **Verificación:** `tests/test_accesibilidad.py` mide los dos bordes contra
  todas las capas, el hover con texto normal y la identidad de la paleta (fondo
  cálido, bordes ocres, acento frío). `tests/test_tema.py` exige los tokens
  nuevos en las dos paletas.

## M5 — Release sin checksums ni SBOM: RESUELTO (2026-11-10)

- **Implementado:** `.github/workflows/build-release.yml` genera `SHA256SUMS`
  (`sha256sum -c` verificable) y, best-effort, `sbom.cdx.json` (CycloneDX) como
  assets del tag. `docs/RELEASE.md` actualizado para reflejarlo.
- **Verificación:** la lógica de checksums se probó localmente
  (`sha256sum tukul-* > SHA256SUMS && sha256sum -c SHA256SUMS`); el YAML se
  validó. Queda pendiente el run real del workflow, bloqueado por H0.

## H0 — CI no ejecuta ningún paso

- Los runs de `935ccb7`, `ee7ca36` y anteriores terminan en 1-4 s con
  `steps: []` y `billable.total_ms = 0`: el runner no se asigna.
- **Comprobado por Playwright:** githubstatus.com muestra *All Systems
  Operational* y el servicio **Actions: Operational**; no es una caída.
- **Cierre:** un run verde con pasos ejecutados.

### Diagnóstico actualizado (2026-11-10)

Reproducido con `gh` sobre `master` y un `workflow_dispatch` fresco
(`42899038794`): los cuatro jobs (`test (3.11/3.12/3.13)` y `security`) salen
`conclusion=failure`, `runner_name=""`, `steps=0`, en ~2-4 s.

- El repositorio es **privado**, con Actions `enabled=true`, workflows `active`
  y sin protección de pinning. No hay nada roto en la definición del workflow.
- Un job que arranca, no obtiene `runner_name` y termina sin pasos es, en un
  repo privado, el patrón de **minutos de Actions bloqueados a nivel de cuenta**
  (límite de gasto alcanzado o método de pago bloqueado). No es corregible
  desde el repositorio.
- **Acción requerida (cuenta/organización, no código):** revisar
  *Settings → Billing → Actions* de la cuenta `IA-Alex`: límite de gasto,
  método de pago y estado de facturación. Alternativa si no se quieren minutos
  de pago: un runner propio (`self-hosted`) o hacer público el repositorio.
- **Mitigación dejada en el repo:** `ci.yml` ejecuta un primer paso que imprime
  `runner.os/arch`, la versión solicitada y `uname -a`. Si vuelve el
  `steps: []`, el patrón es inequívoco; en cuanto haya runner, la traza queda en
  el log.
- **Verificación de cierre:** `gh run list --limit 1` con un run en `success`,
  `steps > 0` y `runner_name` no vacío.
