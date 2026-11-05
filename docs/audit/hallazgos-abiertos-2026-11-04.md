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

## M4 — Contraste no textual de los bordes (pendiente de decidir la paleta)

- **Qué falta:** el token `borde` no alcanza 3:1 (WCAG 1.4.11) contra ninguna capa
  en ninguno de los dos temas:

  | Tema  | fondo | superficie | superficie_alta |
  |-------|-------|------------|-----------------|
  | dark  | 2.95  | 2.32       | 1.97            |
  | light | 2.33  | 2.02       | 2.46            |

- **Por qué no se cambió:** `BORDE` hace tres trabajos a la vez en
  `tukul_ui/app.py` (líneas 540-600): color de bordes y separadores, **fondo de
  hover** de los botones (`("active", es.BORDE)`) y **fondo de la barra de
  desplazamiento activa**. Aclararlo a `#86868A` (dark) / `#66666A` (light) lleva
  los bordes a 3.26-5.48:1 y deja el hover legible, pero las líneas divisorias y
  el sash pasan a ser tan visibles como el texto tenue: cambia el aspecto del
  producto. Es una decisión de diseño, no de código.
- **Evidencia:** `tests/test_accesibilidad.py` (`TestContrasteNoTextual`) mide los
  seis pares y `test_la_deuda_del_borde_es_exactamente_la_declarada` falla si la
  paleta cambia de cumplimiento, para que esta excepción no quede olvidada.
  También se cubren ya con test: foco dentro de los diálogos al abrirlos, cierre
  con Escape devolviendo el foco al editor, y `estado_accesible` para los seis
  estados.
- **Opciones:**
  1. Separar tokens: `borde` (sutil, como hoy) y `borde_control` ≥ 3:1 para
     scrollbar, sash y hover. Es el arreglo correcto y no toca el aspecto
     divisorio.
  2. Aclarar `borde` y aceptar divisorias más marcadas.
- **Cierre:** la constante `_DEUDA_BORDE` de `tests/test_accesibilidad.py` queda
  vacía y el test lo demuestra.

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
