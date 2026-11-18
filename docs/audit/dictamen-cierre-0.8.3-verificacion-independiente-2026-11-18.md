# Dictamen de cierre — Tukul `0.8.3` (verificación independiente)

Fecha: 2026-11-18. Skills: `criterios-de-cierre` + `arquitecto-de-entrega`.
Revisa, con evidencia reproducida en esta sesión, el dictamen de
[`cierre-0.8.3.md`](cierre-0.8.3.md).

## Dictamen

**CIERRE CONDICIONADO.**

Las capacidades esenciales comprometidas en `docs/contracts/contratos-0.8.md`
(F5–F6) están demostradas y los riesgos residuales son aceptables. Queda **una
condición no bloqueante**: la verificación de los evals con una credencial
válida, que hoy no puede reproducirse porque la key del `.env` está revocada.

No equivale a **CERRADO** ni autoriza declarar finalizada la entrega: la
coherencia de versión, la integridad del artefacto y la suite están verificadas,
pero el criterio 5 del DoD del contrato («evals verdes») no es reproducible con
las credenciales actuales.

## Alcance evaluado

- **Propósito:** editor local de Markdown con revisión y conversación asistidas
  por LLM, sin servidor ni base de datos.
- **Capacidades esenciales:** F5 (prompt de sistema por modo) y F6 (defensa
  común compartida y verificada), `docs/contracts/contratos-0.8.md`.
- **Versión:** `0.8.3`. Tag anotado `v0.8.3` sobre `bfae907`.
- **Entornos:** Linux x86_64 (glibc ≥ 2.35); Python 3.11–3.13.
- **Nivel de madurez esperado:** Operativo controlado.

## Evaluación de criterios

| # | Criterio | Estado | Evidencia (reproducida en esta sesión salvo las filas marcadas) |
|---|---|---|---|
| 1 | Funcionalidad | **Cumple** | Suite `904 passed`, 0 omitidas; `--health` OK; CLI rechaza argumentos desconocidos. |
| 2 | Arquitectura | **Cumple** | *(citada del acta)* `ruff` limpio; `mypy` sin incidencias en 69 archivos; `tukul_core` importable en instalación aislada. |
| 3 | Seguridad | **Cumple** | *(citada del acta)* `bandit -lll -ii` verde; `pip-audit` «No known vulnerabilities found»; tabla THREAT/ASSET de `docs/SECURITY.md` con control y test por fila. |
| 4 | Fiabilidad | **Cumple** | Un único evento de control por petición (invariante documentada, con suite); degradación por fuente en feeds. |
| 5 | Persistencia | **Cumple** | Escritura atómica; `test_lockfiles_equivalentes` 3/3; cotas de estado cubiertas. |
| 6 | Integraciones | **Parcial** | Proveedor LLM: el adaptador traduce `401/403` (regresión reproducida: falla con código previo, pasa con el fix). Evals contra proveedor real: **no reproducibles hoy** (401). |
| 7 | Rendimiento | **Cumple** | Sin regresiones; cotas de bytes/línea/body en SSE y respuesta. |
| 8 | Compatibilidad | **Cumple** | *(citada del acta)* CI verde en 3.11, 3.12 y 3.13 (`run 44222206831`, success). |
| 9 | Reproducibilidad | **Cumple** | `uv.lock` == `requirements-dev.lock` (test 3/3); `uv lock --check` limpio; instalación aislada desde sitio sin `.venv`/`conftest`. |
| 10 | Validación adversarial | **Parcial** | Baterías de inyección con arnés reproducible (`promptfoo@0.125.1` descarga OK) y resultados 100 % registrados el 2026-11-17; no reproducibles hoy por credencial. |
| 11 | Regresiones | **Cumple** | El test del 401 falla con el adaptador previo (`AttributeError: CredencialInvalidaError`) y pasa con el actual: patrón «falla antes / pasa después» confirmado. |
| 12 | Observabilidad | **Cumple** | Log JSON rotativo 512 KB + 2 backups; `--health` accionable; `--config` llega al diagnóstico. |
| 13 | Consistencia de entrega | **Cumple** | *(citada del acta; `git describe` no reejecutado)* `pyproject.toml` = `uv.lock` = binario = `0.8.3`; `sha256sum -c` → «La suma coincide»; `cosign verify-blob --bundle` → **Verified OK** (identidad de workflow + emisor OIDC). |
| 14 | Documentación | **Cumple** | CHANGELOG `[0.8.3]`, contrato, `POLITICA_CONGELACION.md` y dictámenes describen el mismo estado; ADR-0005 registra H2 como no-defecto. |
| 15 | Control de alcance | **Cumple** | `0.8.3` agrupa 2 defectos confirmados y 1 retiro sin consumidor; sin funciones nuevas. |
| 16 | Aceptación final | **Parcial** | Gate, CI, artefacto y versión aprobados; la aceptación de los evals queda pendiente por credencial. |

Comando de gate reproducido: `./scripts/quality-gate.sh` →

```text
✓ QUALITY GATE PASSED
904 passed, 1 warning in 278.40s
938 pruebas registradas, 0 omitidas
Total coverage: 87.40%
```

## Hallazgos y bloqueos

| ID | Severidad | Capacidad afectada | Impacto operativo | Evidencia | ¿Bloquea? |
|---|---|---|---|---|---|
| H-401 | Media | Evals (criterio 5 del DoD) | Las 4 baterías `promptfoo` no pueden ejecutarse; todas saldrían 0/N por autenticación. No afecta al producto: el flujo del usuario no consume el eval. | Llamada directa al endpoint con la key del `.env`, ambos alias → `HTTP 401 {"code":"invalid_api_key"}`. | **No.** Es credencial externa caducada, no defecto de código; el adaptador ya la explica accionablemente. |
| C3 | Baja | Accesibilidad con lector de pantalla | Ningún lector de pantalla puede leer los widgets de Tukul. | `verificar_atspi.py` reproducido: «la app no apareció en el árbol AT-SPI». Tk 9.0 no implementa el bridge. | **No.** Verificado como *no expuesto*, no como incumplido; abrir accesibilidad exige contrato nuevo. |
| H2 | Baja | Deuda de mantenibilidad de `app.py` | `tukul_ui/app.py` = 2 710 líneas (objetivo ADR-0005: < 2 300). | `wc -l`; ADR-0005 lo declara no-defecto y objetivo reevaluable. | **No.** Documentado como deuda aceptada. |

No hay defectos **críticos** ni **altos** sin resolver.

## Riesgos aceptados y pendientes

- **Credencial de eval revocada (H-401):** riesgo aceptado por el usuario en el
  cierre de `0.8.3`; mitigación = aportar una key válida y reejecutar las cuatro
  baterías. Seguimiento hasta que exista credencial válida.
- **C3 (accesibilidad):** aceptado explícitamente como límite de plataforma.
- **H2 (deuda de `app.py`):** aceptado como no-defecto (ADR-0005).

## Nota de verificación del entorno

Esta sesión reprodujo el control positivo de AT-SPI y **falló**
(«el bus AT-SPI no ve ni a zenity»), señal de que el sandbox headless no expone
árbol accesible de forma fiable. Por tanto, el resultado «Tukul no aparece» es
**coherente pero no concluyente** en este sandbox; la evidencia sólida de C3 es
el informe de 2026-11-17 en un entorno con escritorio real.

## Mejoras fuera del cierre

- Reactivar la credencial de eval y adjuntar el reporte de las cuatro baterías al
  acta de cierre.
- Reevaluar H2 al retirar los *shims* de compatibilidad.

## Condiciones de cierre

1. **Ejecutar las cuatro baterías `promptfoo@0.125.1`** con una credencial
   válida y anexar el resultado (esperado: 100 % según el registro del
   2026-11-17). Evidencia de aceptación: salida del comando con PASS por caso.

## Recomendación final

Mantener el estado **CERRADO en lo verificable** del acta de `0.8.3` como
**cierre técnico condicionado**: no hay bloqueo de código y el artefacto está
íntegro y firmado. Antes de tratar la entrega como exposición pública de los
evals, restaurar la credencial y correr las baterías; es la única condición
pendiente y no requiere tocar el producto.
