# Hallazgos abiertos de la auditoría 2026-11-04

Estado al 2026-11-04, tras `0320bd9`. Lo que sigue no está corregido; cada
punto dice qué falta, qué evidencia lo sostiene y cuándo se puede cerrar.

## H2 — `TukulApp` concentra la UI y el ciclo de petición (3.085 líneas)

- **Qué falta:** extraer `RequestLifecycle` (los cuatro `def work` inline) y
  `UIStateBookkeeper` a módulos propios.
- **Evidencia:** `wc -l tukul_ui/app.py` → 3.085; `grep -n "WorkerThreads.start"` →
  4 llamadas; cobertura de `app.py` 74 %.
- **Bloqueo:** es una extracción de varias sesiones. Los tests de cola, reentrada
  y cierre son la red de seguridad y deben pasar **sin cambios**.
- **Cierre:** `app.py` < 2.300 líneas y cobertura del nuevo módulo ≥ 90 %.

## M4 — Contraste no textual de los bordes: RESUELTO (2026-11-04, segunda pasada)

- **Origen:** el token `borde` hacía tres trabajos a la vez (divisoria, fondo de
  hover y fondo de scrollbar) y no alcanzaba 3:1 contra ninguna capa.
- **Decisión de producto:** la paleta se rehízo a partir de la identidad del
  nombre. Tukul es la casa redonda de barro y paja del sur de Etiopía; de ahí
  salen las capas de barro cálido, el ocre de paja de las divisorias y el azul
  de la luz de la puerta como único acento.
- **Separación de tokens:** `borde` (divisoria y hover, ahora ≥ 3:1 contra las
  tres capas) y `borde_control` (bordes de botones, campos, sash y barra de
  desplazamiento, ≥ 3:1). El hover de los botones pasa a `superficie_activa`,
  una superficie propia, para no depender del borde.
- **Verificación:** `tests/test_accesibilidad.py` mide los dos bordes contra
  todas las capas, el hover con texto normal y la identidad de la paleta (fondo
  cálido, bordes ocres, acento frío). `tests/test_tema.py` exige los tokens
  nuevos en las dos paletas.

## M5 — Release sin checksums ni SBOM

- **Qué falta:** `SHA256SUMS` y `sbom.cdx.json` como assets del tag.
- **Bloqueo:** se toca `.github/workflows/build-release.yml`, y el runner no está
  aceptando jobs: no habría forma de verificar el cambio.

## H0 — CI no ejecuta ningún paso

- Los runs de `935ccb7`, `ee7ca36` y anteriores terminan en 1-4 s con
  `steps: []` y `billable.total_ms = 0`: el runner no se asigna.
- **Comprobado por Playwright:** githubstatus.com muestra *All Systems
  Operational* y el servicio **Actions: Operational**; no es una caída.
- **Cierre:** un run verde con pasos ejecutados.
