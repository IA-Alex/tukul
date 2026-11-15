# Corte de `0.7.1` — corrección visual y condiciones de cierre

Sesión del 2026-11-15. Skills: `criterios_de_cierre` + `arquitecto_de_entrega`.
Nivel de madurez evaluado: **Operativo controlado**.

## Por qué un parche y no continuación de `0.7.0`

`0.7.0` quedó tageada sobre `e13efd6`, pero el trabajo de corrección visual se
hizo **después**: HEAD estaba en `v0.7.0-1-g5c6b8d4` con cuatro módulos
modificados sin commitear y un módulo de pruebas sin versionar.

Por la clasificación de [`docs/POLITICA_CONGELACION.md`](../POLITICA_CONGELACION.md)
esto es un **defecto confirmado**, no una función nueva: el comportamiento
observable no cumplía lo prometido (panel sin desbordes, acciones completas,
nombre del artículo visible). Encaja en `0.7.x`; no reabre el contrato.

## Defectos corregidos y su evidencia de regresión

Cada prueba de `tests/test_visual_regresion.py` se comprobó **en ambas
direcciones**: con `git stash push -- tukul_ui/` (código previo) y sin él.

| Prueba | Código previo | Corrección | Tipo |
|---|---|---|---|
| Panel no pide más ancho que la ventana | FAIL (`906 > 386`) | PASS | Regresión |
| «Cancelar» conserva su texto entero | FAIL (`52 < 143`) | PASS | Regresión |
| Guía ajusta su salto al ancho real | FAIL (`no guia_label`) | PASS | Regresión |
| Textos usan la superficie en que viven | FAIL (`TenueSuperficie`) | PASS | Regresión |
| Divisor fino sin marcas de agarre | FAIL (`10 > 2`) | PASS | Regresión |
| Reparto de la barra (3 pruebas) | FAIL (`no _desplazamiento_por_ancho`) | PASS | Regresión |
| Fila vuelve a reposo al terminar | PASS | PASS | **Invariante** |
| Divisor mantiene 3:1 (WCAG 1.4.11) | PASS | PASS | **Invariante** |

Las dos invariantes se declaran como tales en su propia docstring: se dejaron
como vigilancia de que la corrección no rompe algo ya correcto, pero no
prueban una regresión y no deben contarse como tal.

## Medición en ventana real (Tk sobre Xvfb)

Barra superior, con el nombre del artículo y las piezas visibles:

| Ancho | Nombre | Estado | Contexto/Modelo/Tema |
|---|---|---|---|
| 1120 | 574 px | oculto | ocultos |
| 1200 | 529 px | visible | ocultos |
| 1279 | 608 px | visible | ocultos |
| 1280 | 164 px | visible | visibles |
| 1600 | 484 px | visible | visibles |

Ida y vuelta `1120 → 1600 → 1120` deja el mismo estado: el reparto es
reversible, no acumulativo.

## Contraste (WCAG 1.4.11 y AA)

| Combinación | Oscuro | Claro |
|---|---|---|
| `texto_tenue` sobre `superficie_alta` | 6.09 | 7.70 |
| `borde_control` sobre `fondo` (sash) | 3.78 | 3.60 |

## Gate

`./scripts/quality-gate.sh` → **`✓ QUALITY GATE PASSED`**

- **837 passed**, 862 pruebas registradas, **0 omitidas**.
- Cobertura total **87.66 %** (mínimo 70 %).
- `ruff` y `mypy` limpios (68 archivos).
- Instalación aislada, `--health`, `--config`, CLI, `pip-audit`, `bandit` y
  lockfile con hashes: verdes.

## Coherencia de versión

`pyproject.toml` = `uv.lock` = `--health` = **`0.7.1`**; `uv lock --check`
limpio, sin cambios de dependencias (el diff del lockfile es solo la versión
del proyecto). Los `.egg-info` desincronizados se corrigieron reinstalando en
editable.

## Condiciones de cierre abiertas

Ninguna es código. Todas son acciones externas pendientes de confirmación del
mantenedor:

1. **Push** de `master` + tags (la rama va por delante de `origin/master`).
2. **Release firmada** `v0.7.1` por CI.
3. **Verificación en destino** sobre lo descargado: `sha256sum -c SHA256SUMS`,
   `--health`, `cosign verify-blob`.
4. **Dictamen CERRADO** con esa evidencia.

Hasta que se cumplan, el dictamen es **CIERRE CONDICIONADO**: el código está
demostrado, el artefacto entregable no existe todavía.

## Riesgos aceptados

- **C3 — lector de pantalla:** sin host con Orca; no verificado, no incumplido.
- **C4 — sostenibilidad de proveedores:** descriptivo, sin umbral.
- **H2 — `app.py < 2 300`:** 2 634 líneas; declarado no-defecto (ADR-0005).
- **`ANCHO_SECUNDARIOS = 1280`:** umbral medido empíricamente; con zoom o fuente
  distinta el punto de giro cambia. Deuda con trigger: primer reporte de
  desborde visual.
- **Integraciones:** sin consulta real a proveedores externos en esta sesión; la
  evidencia es la suite y la degradación ya cubierta.

## Reparación de hallazgos de la auditoría de cierre (2026-11-15)

Segunda pasada con `criterios_de_cierre` + `reparador-integral-es` sobre el
mismo HEAD, tras confirmar con un clon independiente que el repositorio público
sigue en `0.6.1`. Los hallazgos de código y documentación se cerraron aquí; el
de entrega (H-1) requiere push y Release, que son acciones externas.

| Hallazgo | Severidad | Estado | Evidencia |
|---|---|---|---|
| **H-1** Remoto sin `0.7.x` (20 commits, sin tag ni Release) | Crítica | **Abierto** — acción externa | `git ls-remote --tags origin 'refs/tags/v0.7*'` vacío; último Release `v0.6.1` |
| **H-2** DoD 2 y 3 del contrato citaban `0.7.0` | Media | **Corregido** | `contratos-0.7.md` §DoD ahora nombra la versión de entrega (`0.7.1`) y el tag que la contiene |
| **H-3** Métrica de `app.py` desactualizada (2 622) | Baja | **Corregido** | Contrato y riesgos dicen 2 634 (`wc -l` sobre `app.py`) |
| **H-4** F4 (isotipo 18 px) sin prueba de regresión | Baja | **Corregido** | `test_el_isotipo_de_la_cabecera_mide_18_px`; falla con `LOGO = 24`, pasa con 18 |
| **H-5** `test_worker_threads.py` no invocaba `publicar_en_hilo_ui` | Baja | **Corregido** | `TestPublicarEnHiloUI` (5 pruebas); 4 fallan con las guardas neutralizadas |
| **H-6** Procedimiento de `POLITICA_CONGELACION.md` hablaba solo de `0.7.0` | Baja | **Corregido** | Procedimiento de corte ahora cubre `0.7.x` |

**Gate tras la reparación:** `✓ QUALITY GATE PASSED` — **843 passed**, 868
pruebas registradas, **0 omitidas**, cobertura total 87,66 %; ruff, mypy,
instalación aislada, `--health`, `pip-audit` y `bandit` verdes.

**Nota de verificación (H-5).** No se pudo provocar un `TclError` fiel desde
Python: con Tk moderno, ni `root.destroy()` ni `Tk_DeleteInterp` hacen fallar
`after()`. El guard de `TclError` se prueba por su frontera (un `after` que la
lance) y el `RuntimeError` con su valor literal. El test no simula un Tk roto
que no ocurre en esta plataforma; fija el contrato observable del helper.

**Estado del dictamen:** se mantiene **CIERRE CONDICIONADO**. El código y la
documentación están reparados y verificados; el artefacto entregable sigue sin
existir. Pasa a **CERRADO** cuando se cumplan las condiciones de
`docs/contracts/contratos-0.7.md` §«Condiciones de cierre abiertas».
