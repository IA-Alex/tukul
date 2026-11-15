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
