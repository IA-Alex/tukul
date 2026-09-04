# Release

## Contrato reproducible

**PRECONDITIONS:** árbol revisado, versión en `pyproject.toml`, `CHANGELOG.md` actualizado y quality gate local verde.

**VERSIONING:** Semantic Versioning en la metadata del proyecto y tags `vX.Y.Z`. Cambios incompatibles deben quedar en CHANGELOG.

**QUALITY_GATE / CI / SECURITY_SCAN:** ejecuta `./scripts/quality-gate.sh`; CI debe pasar en Python 3.11–3.13, `pip-audit` sin hallazgos bloqueantes y Bandit high/high sin hallazgos.

**BUILD:** `.github/workflows/build-release.yml` construye con PyInstaller en runners nativos y ejecuta `--health` del binario. Los artefactos actuales son `articulador-linux-x86_64` y `articulador-windows-x86_64.exe`; macOS no es target verificado ni soportado por este workflow.

**SMOKE_TEST / ARTIFACTS:** el smoke test es `--health`; se suben los dos binarios como artifacts y, para un tag, como GitHub Release. **CHECKSUMS** y **SIGNING_IF_AVAILABLE** no están implementados por el workflow actual; no deben anunciarse como garantías.

**PUBLISH:** empuja un tag `vX.Y.Z`; el job `release` publica solo en tags y requiere `contents: write`. Un `workflow_dispatch` construye artifacts sin publicar Release.

**ROLLBACK:** retira o marca el Release afectado y comunica el tag/binario anterior conocido; no sobrescribas archivos de usuario. **POST_RELEASE_VALIDATION:** descarga ambos assets, ejecuta `--health` en cada plataforma y conserva el run/artifacts del workflow.
