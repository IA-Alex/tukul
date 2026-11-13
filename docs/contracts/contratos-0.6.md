# Modelo — Cuatro contratos de cierre para después de `0.5.2`

Estado: **C1-C4 con decisión tomada; C2 ejecutado y verificado** (2026-11-13).
La versión congelada `0.5.2` no se toca. Las decisiones de C1, C3 y C4 las fijó
el mantenedor; C2 se ejecutó en la rama de trabajo y queda pendiente de release.

## Por qué un modelo y no cuatro contratos definitivos

Seguí `criterios_de_cierre`: cerrar exige un contrato con capacidades
verificables y evidencia de aceptación concreta. Tres de los cuatro candidatos
dependen de decisiones o recursos que hoy no existen:

| Contrato | Bloqueo externo real | Consecuencia |
|---|---|---|
| **C1** — Firma de binarios | Decidido: cosign keyless | **Implementado**; falta el primer run OIDC real |
| **C2** — `app.py` bajo 2.300 líneas | Ninguno | **Ejecutado**: 2.640 → 2.590 (−50) |
| **C3** — Accesibilidad con lector de pantalla | Sin host con Orca | Solo cerrable como Experimental, con limitación declarada |
| **C4** — Sostenibilidad de proveedores | Sin umbral por decisión | Descriptivo; no se puede dictaminar |

Las decisiones que estaban marcadas como pendientes ya están tomadas (ver
«Decisiones del mantenedor»). Nada de este documento afirma un resultado que no
se haya observado; cada afirmación numérica se midió en este repositorio.

---

## C1 — Firma verificable de los binarios de release

- **Origen:** S1, aceptado como riesgo residual en `docs/RELEASE.md` y en
  `docs/audit/hallazgos-abiertos-2026-11-04.md`.
- **Estado actual (observado):** `.github/workflows/build-release.yml` no
  contiene ningún paso de firma. La Release publica `SHA256SUMS` y
  `sbom.cdx.json`; ambos viajan por el mismo canal HTTPS que el binario.
- **Contexto de ejecución relevante (observado):** el job `release` declara solo
  `permissions: contents: write`; no tiene `id-token: write`. La firma keyless de
  `cosign` **exigiría añadir ese permiso** al job (decisión de seguridad, no un
  detalle de implementación).
- **Propósito:** que un usuario pueda demostrar que el binario descargado salió
  de este repositorio y no de un canal intermedio, sin depender de HTTPS.
- **Capacidad esencial:** una firma publicada junto al binario, verificable con
  un procedimiento documentado, y el binario rechazado si la firma no valida.
- **Fuera de alcance:** notarización de SO, firma de paquetes Python, Windows y
  macOS.
- **Criterio de aceptación:**
  1. El workflow falla si no puede firmar (nunca publica un binario sin firma).
  2. El procedimiento de verificación está en `docs/RELEASE.md` y lo ejecuta
     alguien distinto del autor sobre una descarga real.
  3. Se retira la nota de riesgo residual aceptado.
- **Decisión tomada (mantenedor, 2026-11-13):** **cosign keyless** con la
  identidad OIDC de GitHub. Implica añadir `id-token: write` al job `release`,
  publicar `tukul-linux-x86_64.sig` y `.pem` junto al binario, y documentar
  `cosign verify-blob` con `--certificate-identity-regexp` y
  `--certificate-oidc-issuer` del repositorio.
- **Riesgo de arrancar sin decisión:** el contrato nace con un bloqueo
  incorporado, el mismo error que impidió cerrar antes.

## C2 — Reducir `app.py` por debajo de 2.300 líneas

- **Origen:** H2, en `docs/audit/hallazgos-abiertos-2026-11-04.md`.
- **Estado actual (observado):** `tukul_ui/app.py` tiene **2.640 líneas**. Hacen
  falta **341** para alcanzar el objetivo y (~390) para dejarlo holgado.
- **Criterio ya declarado:** `app.py` < 2.300 líneas y cobertura del módulo
  extraído ≥ 90 %.
- **Candidato de extracción (propuesta, a validar con los tests):** el bloque de
  documentos al final de la clase —`save_document`, `save_project`,
  `open_project`, `_enter_document_scope`— hoy delega en `DocumentManager` y
  `DocumentScope`, así que el estado que arrastra es pequeño. No es una cifra
  comprometida hasta que el refactor demuestre la cobertura.
- **Capacidad esencial:** el comportamiento observable no cambia; la suite
  completa sigue verde con las mismas pruebas de contrato.
- **Riesgo principal:** los tests parchean métodos de `TukulApp`. Una extracción
  que mueva el punto donde se parchea convertiría pruebas en decoración. El
  cierre exige revisar cada `patch` afectado, no solo que pasen.
- **Fuera de alcance:** rediseño de la UI, renombrado de métodos públicos, cambio
  de arquitectura más allá de lo necesario para bajar el número.

## C3 — Accesibilidad verificada con lector de pantalla real

- **Origen:** mejora declarada como no verificada en los dictámenes de cierre.
- **Estado actual (observado):** `tests/test_accesibilidad.py` mide contraste
  WCAG AA, cierre de diálogos y foco devuelto. **No** hay prueba con AT-SPI ni
  con Orca.
- **Capacidad esencial:** un recorrido guiado con Orca en el que se pueda
  (a) leer la barra superior y el documento, (b) navegar los botones principales
  y (c) completar un envío y una revisión sin depender solo del ratón.
- **Criterio de aceptación:** transcripción del recorrido con nombre de cada
  control anunciado, los fallos encontrados clasificados y corregidos o aceptados
  con justificación, y una prueba automatizada mínima que detecte la regresión
  más grave encontrada.
- **Decisión tomada (mantenedor, 2026-11-13):** **no hay host con Orca**; solo
  el host headless actual.
- **Consecuencia:** C3 no puede cerrarse como *Operativo controlado*. Queda
  como **Experimental** con la limitación declarada (contraste, foco y foco
  devuelto verificados; *lector de pantalla no verificado*) hasta que exista un
  entorno con Orca. No se abre hasta que ese entorno exista.

## C4 — Sostenibilidad de los proveedores externos

- **Origen:** "cuotas de proveedor en uso sostenido: no verificado" en todas las
  auditorías del conector.
- **Estado actual (observado):** hay manejo de 429, `Retry-After`, backoff y
  degradación por fuente. No hay evidencia de comportamiento durante uso
  prolongado ni de coste por sesión.
- **Capacidad esencial:** uso repetido de la app durante un periodo acordado sin
  fallos no explicables, con los límites de cada proveedor y el coste observado
  registrados.
- **Decisión tomada (mantenedor, 2026-11-13):** **sin umbral** por ahora.
- **Consecuencia:** C4 no se puede dictaminar; queda **descriptivo**. Si se
  abre, será para registrar observaciones (latencias y errores por proveedor),
  no para cerrar. No es trabajo de ingeniería hasta que haya un umbral.

---

## Estado de C2 (ejecutado el 2026-11-13)

- **Qué se hizo:** los flujos `save_project`, `open_project` y
  `_enter_document_scope` se movieron a `tukul_ui/proyectos.py`, con un
  `Protocol` (`VentanaDeProyectos`) que declara la superficie que necesitan de
  la ventana. `TukulApp` conserva los tres métodos como delegaciones finas.
- **Medición:** `wc -l tukul_ui/app.py` → **2.640 → 2.590** (−50 líneas).
- **Cobertura del módulo nuevo:** **97 %** (2 líneas sin cubrir), por encima
  del ≥ 90 % que pedía H2.
- **Gate:** 753 pruebas, 0 omitidas, cobertura total 88,58 %, ruff/mypy/
  instalación/pip-audit/bandit verdes.
- **Hallazgo destapado por la extracción:** `open_project` rellenaba el editor
  con el artículo de la sesión ANTERIOR en vez del cargado del proyecto. Se
  corrigió y se fijó con `test_restaura_el_artículo_del_proyecto_y_no_el_anterior`,
  comprobado en ambas direcciones (falla con el bug, pasa con la corrección).
- **Objetivo < 2.300:** **no alcanzado** (−50 de 341 necesarias). Este bloque
  era el más desacoplado; llegar al objetivo exige extraer también el ciclo de
  petición, lo que toca el contrato de streaming y queda fuera de este paso.
  C2 sigue **parcial**.

## Estado de C1 (implementado el 2026-11-13)

- **Implementado:** `id-token: write` en el job `release`, `cosign-installer`
  v4.1.3 fijado por SHA, `cosign sign-blob --bundle` (cosign 3.x eliminó
  `--output-signature`/`--output-certificate`, comprobado con `sign-blob
  --help` sobre v3.1.4), verificación en el job contra la identidad del
  workflow y el emisor OIDC, y publicación solo si ambas pasan. Sin
  `continue-on-error` ni `|| true`.
- **Verificado en local:** `scripts/verify-signature.sh v0.5.2` falla en rojo
  porque la release no trae `.bundle` (exit 1); 7 pruebas nuevas sobre el YAML
  real; gate completo verde (760 pruebas).
- **Pendiente de evidencia real:** un `workflow_dispatch` que obtenga un
  certificado OIDC **de verdad**. Hasta entonces no se puede afirmar que la
  cadena Fulcio/Rekor funcione: solo que el procedimiento es correcto y que
  falla cerrado.
- **Condición de cierre de C1:** run `workflow_dispatch` verde con los pasos
  *Sign* y *Verify* ejecutados, y `scripts/verify-signature.sh` verde sobre la
  primera release firmada.

## Secuencia propuesta

1. **C1** (cosign keyless): decidido, listo para implementar. Es el único con
   impacto de seguridad y criterio verificable en destino.
2. **C2** (segunda etapa): no se descarta, pero ningún contrato promete la
   cifra < 2.300 dentro de este paso.
3. **C3**: bloqueado hasta que exista un host con lector de pantalla.
4. **C4**: descriptivo, sin umbral; no se abre.

## Decisiones del mantenedor (2026-11-13)

| Tema | Decisión |
|---|---|
| Mecanismo de firma (C1) | cosign keyless con OIDC de GitHub |
| Entorno con lector de pantalla (C3) | no disponible; solo host headless |
| Umbral de sostenibilidad (C4) | sin umbral por ahora |
| Ejecución de C2 | autorizada y ejecutada; resultado parcial (arriba) |
