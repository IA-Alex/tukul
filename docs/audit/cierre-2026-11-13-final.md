# Dictamen de cierre — Tukul `0.6.0` (2026-11-13, final)

Skill: `criterios_de_cierre`. Evaluación de la entrega publicada, verificada
sobre el artefacto descargado, no sobre el código del repositorio.

## Dictamen

**CERRADO.**

## Alcance evaluado

- **Propósito:** editor conversacional local de Markdown con LLM remoto opcional.
- **Versión:** `0.6.0` — tag anotado `3e78ce6`, commit `e22a613`.
  `git describe --tags` → **`v0.6.0` limpio**.
- **Entregado:** `tukul-linux-x86_64`, `tukul-linux-x86_64.bundle`,
  `SHA256SUMS`, `sbom.cdx.json`.
- **Entornos:** Debian 13 / glibc 2.41 (ejecución); CI `ubuntu-latest`
  3.11/3.12/3.13; build `ubuntu-22.04` (glibc 2.35).
- **Nivel de madurez:** Operativo controlado.

## Evaluación de los 16 criterios

| # | Criterio | Estado | Evidencia |
|---|---|---|---|
| 1 | Funcionalidad | **Cumple** | Gate: 764 pruebas, 0 omitidas, cobertura 88,58 %. Binario descargado: `--health` exit 0. |
| 2 | Arquitectura | **Cumple** | Flujos de proyecto extraídos a `tukul_ui/proyectos.py` con `Protocol`. H2 sigue parcial (2.590 vs 2.300): mejora aceptada, no requisito. |
| 3 | Seguridad | **Cumple** | Job `security` verde. Firma keyless verificada: SAN `...build-release.yml@refs/tags/v0.6.0`, emisor `sigstore-intermediate`, 1 entrada Rekor. |
| 4 | Fiabilidad | **Cumple** | Escritura atómica, degradación por fuente, `open_project` corregido y con regresión fijada en ambas direcciones. |
| 5 | Integraciones | **Cumple** | Consultas reales a las cinco fuentes; CI de release verde de punta a punta. |
| 6 | Persistencia | **Cumple** | Tests de persistencia y autosave verdes. |
| 7 | Rendimiento | **Cumple** | Suite ~46 s; cache de MITRE vigente. |
| 8 | Compatibilidad | **Cumple** | Binario `0.6.0` ejecutado en glibc 2.41, exit 0. Suelo 2.35 verificado en build. |
| 9 | Reproducibilidad | **Cumple** | `sha256sum -c SHA256SUMS` → «La suma coincide». |
| 10 | Validación adversarial | **Cumple** | Suite de seguridad, DTD, SSE acotado, rutas maliciosas. |
| 11 | Regresiones | **Cumple** | 11 pruebas sobre el YAML de release; regresión del glob comprobada en ambas direcciones. |
| 12 | Observabilidad | **Cumple** | Log rotativo; `--health` con versión; el fallo de `v0.6.0` quedó diagnosticado por el propio CI. |
| 13 | Consistencia de entrega | **Cumple** | Tag = HEAD = `e22a613`; artefacto firmado; `.bundle` presente. |
| 14 | Documentación | **Cumple** | `RELEASE.md` documenta la firma real; `contratos-0.6.md` con estados honestos. |
| 15 | Control de alcance | **Cumple con aviso** | El alcance se extendió tras `0.5.2` y se cerró en `0.6.0`. Requirió un ciclo extra por un defecto propio del CI. |
| 16 | Aceptación final | **Cumple** | Funcional, integración, seguridad y firma aprobadas sobre el artefacto. |

## Lo que falló y cómo se resolvió

- **Run `43480365838` (fallo):** el glob `dist/tukul-*` incluía el `.bundle`
  recién creado y el job intentó verificar `...bundle.bundle`. La firma en sí
  verificó OK; **el job falló cerrado y no publicó**, como está diseñado.
- **Corrección:** patrón `dist/tukul-*[!e]` + `test_el_patron_de_firma_excluye_el_bundle`,
  comprobado en ambas direcciones.
- **Run `43481029987` (verde):** Sign, Verify y Publish exitosos; Release
  publicada con los 4 assets.

## Riesgos residuales aceptados

- **Notarización de SO:** no aplica (solo Linux).
- **C3 (lector de pantalla):** sin host con Orca; sigue no verificado.
- **C4 (sostenibilidad de proveedores):** sin umbral; no dictaminable.
- **Cobertura:** `contexto_dialogo.py` al 60 %; por debajo del plan original,
  no de la puerta mínima (70 %).
- **Histórico:** las releases anteriores a `0.6.0` no tienen firma.

## Recomendación final

Congelar **`0.6.0`** y detener el desarrollo de este alcance. El contrato se
cumple con evidencia sobre el artefacto distribuido. Cualquier trabajo posterior
(C3, C4, H2 completo) debe abrir un contrato nuevo con su propio criterio de
cierre, no reabrir `0.6.0`.

La congelación **admite descongelación únicamente para correcciones** (defecto
confirmado, regresión, fallo de seguridad o fallo de entrega), publicadas como
`0.6.x`. Procedimiento y límites en
[`docs/POLITICA_CONGELACION.md`](../POLITICA_CONGELACION.md).

## Correcciones posteriores sobre `0.6.0`

El dictamen sigue siendo **CERRADO**: nada de lo observado después contradice el
contrato de `0.6.0`, y las correcciones se aplican sobre la rama de versión, sin
reabrirla.

### Ciclo conector-proveedor (2026-11-13)

- **Auditoría de origen:**
  [`auditoria-conector-proveedor-2026-11-13.md`](auditoria-conector-proveedor-2026-11-13.md)
  (serie `C-01..C-03`, distinta de los `H-01..H-08` de
  [`auditoria-conector-2026-11-12.md`](auditoria-conector-2026-11-12.md) para no
  colisionar rótulos).
- **Correcciones:** C-01 (doc del perfil `deepinfra` con id real y regresión),
  C-02 (docstring del adaptador de evaluación fiel a su muestreo), C-03 (el
  cliente propaga el `error.message` del proveedor con lectura acotada).
- **Evidencia previa al tag:** gate verde — **780 pruebas, 0 omitidas,
  cobertura 88.58 %**; `ruff` y `mypy` limpios. La regresión de C-01 se comprobó
  en ambas direcciones (falla con la doc anterior, pasa con la corrección).
- **Publicación:** parche `0.6.1` (tag `v0.6.1`), sin funciones nuevas. La
  verificación en destino (`sha256sum -c`, `--health`, `cosign verify-blob`
  sobre el artefacto descargado) se registra al completarse el ciclo.
- **Registro:** entrada `[0.6.1]` en [`CHANGELOG.md`](../../CHANGELOG.md).

