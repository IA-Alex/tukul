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

## S1 — Binarios sin firma ni notarización: RIESGO ACEPTADO
- **Qué falta:** los ejecutables se publican con `SHA256SUMS` y SBOM, pero sin
  firma criptográfica (Authenticode en Windows, GPG/cosign para los adjuntos).
- **Riesgo residual:** la integridad depende del canal HTTPS del Release; el
  `SHA256SUMS` viaja por el mismo canal, así que no permite verificar procedencia
  más allá de detectar corrupción. Un atacante con control del canal puede
  sustituir ambos.
- **Decisión:** **aceptado conscientemente** (ver `docs/RELEASE.md`, nota de
  riesgo residual). Implementarlo exige una decisión de producto sobre el
  mecanismo (clave GPG, cosign o certificado Authenticode) y la gestión de sus
  secretos, fuera del alcance actual.
- **Cierre:** implementar la firma, documentar el procedimiento de verificación
  para el usuario y retirar la nota de `docs/RELEASE.md`.

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

### Causa confirmada (2026-11-12)

La anotación del propio job nombra la causa, sin ambigüedad:

```text
The job was not started because recent account payments have failed or your
spending limit needs to be increased. Please check the 'Billing & plans'
section in your settings
```

- **Evidencia:** `gh api repos/IA-Alex/tukul/actions/runs/<id>/jobs` sobre el run
  `43318920600` (push de `0840558`): los cuatro jobs con
  `conclusion=failure`, `runner_name=''`, `steps=0`, y esa anotación en
  `security` y los tres `test (3.11/3.12/3.13)`.
- **Naturaleza:** bloqueo de **facturación de la cuenta**, no del workflow ni del
  código. El `ci.yml` es correcto (el paso «Runner asignado» está bien definido;
  solo no llega a ejecutarse porque no hay runner).
- **Acción (cuenta):** *Settings → Billing & plans* de `IA-Alex` — método de pago
  y límite de gasto de Actions. No modificable desde el repositorio.
- **Alternativas sin minutos de pago:** runner `self-hosted`, o hacer público el
  repositorio (Actions es gratis en repos públicos).
- **Repro del diagnóstico:**
  `gh run list --limit 1` y
  `gh api repos/IA-Alex/tukul/actions/runs/$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')/jobs`
  → buscar `steps=0` y la anotación de facturación.
- **Ayuda en el repositorio:** `./scripts/diagnose-ci.sh` clasifica el último run
  (o uno por id) como bloqueo de cuenta vs. fallo de código, sin depender de
  inspección manual de la API.

### RESUELTO (2026-11-12)

Se adoptó la alternativa «repositorio público»: Actions es gratis en repos
públicos, así que los runners vuelven a asignarse sin minutos de pago.

- **Acción:** visibilidad cambiada a pública (`gh api -X PATCH repos/IA-Alex/tukul
  -f visibility=public`). Antes se verificó que no hubiera secretos versionados:
  `.env` nunca se commiteó (ni en el historial) y las únicas menciones de
  `DEEPINFRA_API_KEY` son el *nombre* de la variable en docs, no el valor.
- **Evidencia de cierre:** run `43328734310` (push de `50df582`) →
  `conclusion=success`; los cuatro jobs con `runner_name` no vacío y `steps` 20
  (test 3.11/3.12/3.13) y 10 (security). Se cumple el criterio de cierre original
  (`success`, `steps > 0`, `runner_name` no vacío).
- **Higiene pendiente:** rotar la `DEEPINFRA_API_KEY` usada en evals locales, ya
  que el repositorio es ahora público (la key no estuvo expuesta, pero conviene
  rotarla por precaución).
- **Hallazgo destapado al desbloquear:** al arrancar el CI apareció un fallo real
  en `tests/test_auditoria_2026_11_12.py` — `_tamano` hacía `split()` del string
  de `cget("font")` y con una familia con espacios («{Nimbus Sans} 12») tomaba
  «Sans}» como tamaño. Solo se manifestaba en entornos sin la fuente del tema
  (el runner), no en local. Corregido en `50df582` con `tkfont.Font.actual("size")`.
