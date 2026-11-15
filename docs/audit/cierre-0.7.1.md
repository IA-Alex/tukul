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

### Publicación y verificación en destino (2026-11-15)

Push ejecutado bajo autorización del mantenedor. `v0.7.1` se recreó sobre el
commit de la reparación (`4e21bcb`) **antes de publicarse**, de modo que el tag
incluye las pruebas y la documentación corregidas. La política prohíbe reescribir
un tag *publicado*; éste nunca lo estuvo, así que no se invalidó ninguna firma
ajena.

- **Push:** `a84660d..4e21bcb  master -> master`; `v0.7.0` y `v0.7.1` como tags
  nuevos. `git ls-remote` confirma `master` = `v0.7.1^{}` = `4e21bcb` local:
  `git describe --tags` → **`v0.7.1` limpio**.
- **Release:** run `43768277054` → **success** (build `ubuntu-22.04`, release).
  Release `v0.7.1` publicada (no draft, no prerelease) con
  `tukul-linux-x86_64` (34 946 728 B), `SHA256SUMS`, `sbom.cdx.json` (116
  componentes) y `tukul-linux-x86_64.bundle`.
- **Verificación en destino** sobre lo descargado con `gh release download`, no
  sobre lo construido:
  - `sha256sum -c SHA256SUMS` → **«La suma coincide»**.
  - `./tukul-linux-x86_64 --health` → **`versión: Tukul 0.7.1`**, exit 0.
  - `cosign verify-blob --bundle … --certificate-identity-regexp
    '…build-release.yml@refs/tags/v0.7.1' --certificate-oidc-issuer
    https://token.actions.githubusercontent.com` → **Verified OK** (cosign
    v3.1.4, la misma versión fijada por el workflow).
- **Capacidades en el artefacto:** el binario embebe
  `tukul_core.real_time_feed.adapters.openalex`,
  `…adapters.huggingface_papers` (F1), los cuatro módulos de
  `tukul_core.memory` (F2) y la capa extraída (`window_shell`, `editor_session`,
  `credentials`, `dialogs_base`, `worker_threads` — DF-001/ADR-0005). La ventana
  abre y cierra con exit 0 bajo Xvfb.

### Hallazgo abierto tras la publicación (CI)

- **H-7 [MEDIA · CONFIRMADO · PREEXISTENTE]:** el job `test` del CI/CD falla en
  3.11/3.12/3.13 (run `43768275379`) con **2 fallos en
  `tests/test_corpus_eval.py`**: el verificador del corpus exige **`aspell`**, que
  no está instalado en el runner (`FALLA aspell — aspell no instalado`), y
  `0/10 artículos PASS` por esa única causa. **No es regresión de `0.7.1`**: el
  mismo fallo aparece en el run `43516862279` de `v0.6.1` con idéntico mensaje.
- **Impacto:** el quality gate local pasa (aquí `aspell` está instalado); el CI
  queda rojo, así que la señal automática de la puerta no es verde aunque la
  Release sí se publique (el workflow de release no depende del job `test`).
- **Acción mínima:** instalar `aspell` en el CI (o declarar el verificador del
  corpus como opcional cuando la herramienta no exista, registrándolo como
  omitido explícito en vez de enmascararlo). Abre parche `0.7.2`: no cambia
  capacidades.

### Resolución de H-7 — `0.7.2` (2026-11-15)

- **Causa raíz:** `aspell` no estaba en el runner de CI y el verificador del
  corpus lo requiere para ortografía real. `shutil.which("aspell")` devolvía
  `None`, el verificador marcaba `FALLA` en los 10 artículos y el job `test`
  caía en las tres versiones de Python. Un fallo de entorno se presentaba como
  contenido roto, por eso pasó desapercibido desde `0.6.1`.
- **Corrección (sin cambio de capacidades):**
  - `ci.yml` instala `aspell` y `aspell-es` junto a `xvfb`/`python3-tk`.
  - `verificar_corpus_eval.py` expone `requerir_aspell()` y nombra la
    herramienta ausente; sigue **fail-closed** (no aprueba sin ortografía).
  - `quality-gate.sh` comprueba `aspell` antes de la suite e imprime la orden
    de instalación.
  - Tres regresiones en `tests/test_corpus_eval.py`.
- **Verificación en ambas direcciones:** sin `aspell` en `PATH` el verificador
  sale 1 y nombra la causa; quitando `aspell-es` del workflow la suite vuelve a
  rojo; el gate local sin `aspell` avisa y falla.
- **Gate:** `✓ QUALITY GATE PASSED` — 846 passed, 871 registradas, 0 omitidas,
  cobertura 87,66 %.
- **CI del commit tageado (run `43769474792`):** **success** en
  `security`, `test (3.11)`, `test (3.12)` y `test (3.13)`. Primera vez verde
  desde `v0.6.0`.
- **Release `v0.7.2` (run `43769476662`):** success. Verificado sobre lo
  descargado: `sha256sum -c` → «La suma coincide»; `--health` →
  `Tukul 0.7.2`; `cosign verify-blob` con SAN del tag `v0.7.2` → **Verified
  OK**.

**Estado del dictamen:** **CERRADO**. Las capacidades esenciales (F1–F4,
refactor DF-001) están publicadas, el artefacto está firmado y verificado en
destino, los hallazgos H-2…H-7 están cerrados y la puerta de calidad es verde
en CI. Procede **congelar `0.7.2`** y detener el desarrollo de este alcance.
La deuda viva (C3 lector de pantalla, C4 cuotas de proveedor, H2 `app.py <
2 300`, umbral `ANCHO_SECUNDARIOS`) sigue siendo no bloqueante y abre contrato
futuro, no reabre éste.
