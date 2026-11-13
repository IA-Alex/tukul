# Release

## Contrato reproducible

**PRECONDITIONS:** árbol revisado, versión en `pyproject.toml`, `CHANGELOG.md` actualizado y quality gate local verde.

**VERSIONING:** Semantic Versioning en la metadata del proyecto y tags `vX.Y.Z`. Cambios incompatibles deben quedar en CHANGELOG.

**QUALITY_GATE / CI / SECURITY_SCAN:** ejecuta `./scripts/quality-gate.sh`; CI debe pasar en Python 3.11–3.13, `pip-audit` sin hallazgos bloqueantes y Bandit high/high sin hallazgos.

> **CI operativo (2026-11-12):** el bloqueo de H0 (jobs con `steps: []` y sin
> runner por facturación de Actions) quedó resuelto al hacer público el
> repositorio, donde Actions es gratuito. Verificado en el run `43328734310`
> (`success`, jobs con `runner_name` no vacío). Detalle en
> `docs/audit/hallazgos-abiertos-2026-11-04.md#resuelto-2026-11-12`.

**BUILD:** `.github/workflows/build-release.yml` construye con PyInstaller y ejecuta `--health` del binario. El único artefacto actual es `tukul-linux-x86_64` (x86_64). Windows y macOS no son targets soportados: Windows se retiró el 2026-11-12 y macOS el 2026-08-17, ambos por no poder validarse en el sistema destino ni existir necesidad declarada.

> **Imagen de build fijada (DF-C1, auditoría de cierre 2026-11-12):** el job usa
> `runs-on: ubuntu-22.04` (glibc 2.35), **no** `-latest`. El sello `-latest` es
> flotante: migró a Ubuntu 26.04 (glibc 2.42) y el binario Linux pasó a exigir
> `GLIBC_2.42`, dejando de arrancar en Debian 13 / Ubuntu 24.04 y anteriores.
> Compilar en la imagen más antigua soportada fija el suelo de glibc. El paso
> `Verify Linux glibc floor` extrae las bibliotecas empaquetadas del binario y
> falla si alguna exige una glibc más nueva que la de la imagen. No usar
> `-latest` en este workflow ni retirar ese paso sin verificar el requisito real
> en un host más antiguo.

**SMOKE_TEST / ARTIFACTS:** el smoke test es `--health`; se suben los dos binarios como artifacts y, para un tag, como GitHub Release junto a `SHA256SUMS` (verificable con `sha256sum -c`) y, best-effort, `sbom.cdx.json` (CycloneDX). El SBOM no es bloqueante: si la herramienta falla, el release sigue siendo válido con los checksums.

**FIRMA (keyless, contrato C1):** además del binario, cada Release publica
`tukul-linux-x86_64.bundle`: firma de cosign en formato bundle con el
certificado efímero emitido por Fulcio a partir del OIDC de GitHub y la prueba
de Rekor. No hay clave privada que custodiar; la firma queda ligada a **este**
repositorio, **este** workflow y la ref firmada. El workflow falla —y por tanto
no publica Release— si la firma o su verificación no pasan. Para comprobarla:

```bash
cosign verify-blob \
  --bundle tukul-linux-x86_64.bundle \
  --certificate-identity-regexp "^https://github.com/IA-Alex/tukul/.github/workflows/build-release.yml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/[^ ]+)$" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  tukul-linux-x86_64
```

`scripts/verify-signature.sh [TAG]` descarga el binario y el bundle de una
Release y ejecuta la verificación más `sha256sum -c`. Un Release sin `.bundle`
no permite comprobar procedencia, solo integridad.

> **Riesgo residual (auditoría 2026-11-10, DF-002) — CERRADO como contrato,
> pendiente de primer tag firmado:** la nota anterior decía que los ejecutables
> se publicaban «sin firma ni notarización». Desde la implementación de **C1**
> (`docs/contracts/contratos-0.6.md`) cada Release firmada publica su `.bundle`
> keyless y el workflow no publica nada si la firma falla. Siguen fuera de
> alcance la **notarización de SO** (no aplica: no hay targets Windows/macOS) y
> que, mientras la última Release publicada sea anterior a C1, sus binarios
> históricos no tienen firma. Al cortar la primera versión posterior, esta nota
> se retira.


**PUBLISH:** empuja un tag `vX.Y.Z`; el job `release` publica solo en tags y requiere `contents: write`. Un `workflow_dispatch` construye artifacts sin publicar Release.

**ROLLBACK:** retira o marca el Release afectado y comunica el tag/binario anterior conocido; no sobrescribas archivos de usuario. **POST_RELEASE_VALIDATION:** descarga ambos assets, ejecuta `--health` en cada plataforma y conserva el run/artifacts del workflow.
