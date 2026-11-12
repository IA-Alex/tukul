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

**BUILD:** `.github/workflows/build-release.yml` construye con PyInstaller en runners nativos y ejecuta `--health` del binario. Los artefactos actuales son `tukul-linux-x86_64` y `tukul-windows-x86_64.exe`; macOS no es target verificado ni soportado por este workflow.

**SMOKE_TEST / ARTIFACTS:** el smoke test es `--health`; se suben los dos binarios como artifacts y, para un tag, como GitHub Release junto a `SHA256SUMS` (verificable con `sha256sum -c`) y, best-effort, `sbom.cdx.json` (CycloneDX). El SBOM no es bloqueante: si la herramienta falla, el release sigue siendo válido con los checksums. **SIGNING_IF_AVAILABLE:** la firma de binarios no está implementada; no debe anunciarse como garantía.

> **Riesgo residual aceptado (auditoría 2026-11-10, DF-002):** los ejecutables se
> publican con checksums y SBOM, pero **sin firma ni notarización** (Authenticode
> en Windows, GPG/cosign para los adjuntos). La integridad depende del canal
> HTTPS del Release; un usuario no puede verificar criptográficamente la
> procedencia más allá de `sha256sum -c` contra un `SHA256SUMS` que viaja por el
> mismo canal. Se acepta de forma consciente hasta que haya una decisión de
> firma (clave GPG, cosign o certificado Authenticode) y su gestión de secretos.
> Al implementarla, retirar esta nota y documentar el procedimiento de
> verificación para el usuario.


**PUBLISH:** empuja un tag `vX.Y.Z`; el job `release` publica solo en tags y requiere `contents: write`. Un `workflow_dispatch` construye artifacts sin publicar Release.

**ROLLBACK:** retira o marca el Release afectado y comunica el tag/binario anterior conocido; no sobrescribas archivos de usuario. **POST_RELEASE_VALIDATION:** descarga ambos assets, ejecuta `--health` en cada plataforma y conserva el run/artifacts del workflow.
