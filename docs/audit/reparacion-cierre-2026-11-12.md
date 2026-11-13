# Reparación integral — cierre 2026-11-12 (DF-C1, DF-C2)

Skill: `reparador-integral-es`. Origen: auditoría de cierre
(`docs/audit/cierre-2026-11-12.md`), dictamen NO APTO con bloqueo DF-C1.

## Causa raíz

**Usar un sello de runner flotante (`ubuntu-latest`) en el job que produce el
binario distribuible.** Evidencia: el run `43348367772` de `build-release.yml`
se ejecutó en `Image: ubuntu-26.04` (glibc 2.42); el binario `v0.4.1` descargado
falla en un host glibc 2.41 con
`ImportError: .../libtcl8.6.so: version 'GLIBC_2.42' not found`, mientras el
binario `v0.3.2` (imagen antigua) arranca en el mismo host. El requisito lo
hereda la `libtcl8.6.so` que PyInstaller empaqueta desde el sistema de build.

- **Segundo defecto (DF-C2, bajo):** referencias a `tests/test_auditoria_regresion.py`,
  dividido en 6 archivos por dominio el 2026-11-12 (S1).

## Suposiciones declaradas

- Se asume `ubuntu-22.04` (glibc 2.35) como suelo de compatibilidad razonable
  (Ubuntu 22.04+, Debian 12+, RHEL/Rocky 9+). El usuario no fijó un mínimo
  distinto.
- Se asume que Windows seguirá un pin análogo (`windows-2022`) por el mismo
  riesgo de sello flotante.

## Baseline (§0)

Registrado antes de editar:

- Repro: `./tukul-linux-x86_64 --health` en host glibc 2.41 → `GLIBC_2.42 not
  found`, exit 1; `articulador-linux-x86_64` (v0.3.2) → exit 0.
- `./scripts/quality-gate.sh` → QUALITY GATE PASSED, 734 pruebas, 0 omitidas,
  cobertura 87.89 %, ruff/mypy/bandit limpios.
- CI `master` verde (runs `43332629639` y anteriores).

## Tabla de impacto

| Componente | Relación (produce/consume) | ¿Requiere cambio? | Motivo |
| :--- | :--- | :--- | :--- |
| `.github/workflows/build-release.yml` (matrix `os`) | produce el binario Linux/Windows publicado | **Sí** | Punto del defecto: sello flotante migró a glibc 2.42 |
| `.github/workflows/build-release.yml` (paso smoke) | valida el binario antes de publicar | **Sí** | No detectaba exceso de requisito de glibc; se añade guard explícito |
| `.github/workflows/ci.yml` | corre tests (no distribuye binario) | No | `ubuntu-latest` aquí solo ejecuta pytest; no produce artefacto público |
| `README.md` | documenta la instalación sin Python | **Sí** | Debe declarar el suelo de glibc real |
| `docs/RELEASE.md` | contrato de release | **Sí** | Registrar el pin y el guard |
| `docs/SECURITY.md` | cita el test del control de endpoint | **Sí** | DF-C2: ruta de test obsoleta |
| `docs/audit/aviso-health-instalacion-virgen-2026-11-05.md` | cita el test del aviso de health | **Sí** | DF-C2: ruta de test obsoleta |
| `docs/audit/cierre-2026-11-12.md` | informe que originó la reparación | **Sí** | Registrar la corrección |
| `tests/test_quality_gate_parity.py` | fija paridad CI↔gate | No | No cubre `build-release.yml`; reverificado en verde |
| `pyproject.toml`, `tukul_core/`, `tukul_ui/` | lógica de la app | No | El defecto es de empaquetado/CI, no de código |

## Cambios

- `build-release.yml`: matrix Linux → `ubuntu-22.04`, Windows → `windows-2022`
  (dependency: punto del defecto).
- `build-release.yml`: paso `Verify Linux glibc floor` que extrae las `.so`
  empaquetadas con `CArchiveReader` y compara su requisito de glibc con el de la
  imagen (dependency: el smoke sobre la nueva imagen no bastaba como guard).
- `README.md`: declara glibc ≥ 2.35 y las distros soportadas (dependency:
  contrato de distribución visible al usuario).
- `docs/RELEASE.md`: nota del pin y del guard (dependency: contrato de release).
- `docs/SECURITY.md`, `docs/audit/aviso-health-...md`: rutas de test corregidas
  (dependency: DF-C2).
- `docs/audit/cierre-2026-11-12.md`: sección «Corrección aplicada».

## Verificaciones

- `./scripts/quality-gate.sh` → **QUALITY GATE PASSED**, 734 passed, 0 omitidas,
  87.89 % (sin cambio vs. baseline).
- YAML de ambos workflows → parsea correctamente; matrix =
  `['ubuntu-22.04', 'windows-2022']`; orden de pasos correcto (build → smoke →
  guard glibc → rename → upload).
- **Guard probado contra binarios reales** (lógica idéntica al paso de CI):
  - sobre `tukul-linux-x86_64` (v0.4.1) → **falla** señalando
    `libtcl8.6.so exige GLIBC_2.42 > 2.41` (habría bloqueado el release roto);
  - sobre `articulador-linux-x86_64` (v0.3.2) → **pasa** (máx. GLIBC_2.29).
- `git diff` revisado: solo cambios de workflow y documentación; sin cambios
  accidentales; Python intacto.

### No verificado en local

- Ejecución real del workflow de release con el nuevo pin: se delega al run de
  CI (ver «Verificación end-to-end»). Sin Xvfb/Windows aquí no se puede simular
  el runner en local.

## Verificación end-to-end

Tag `v0.4.2` → `build-release.yml` en `ubuntu-22.04` / `windows-2022`; se
comprueba: smoke `--health` verde en ambos, guard de glibc verde, Release
publicado, `sha256sum -c SHA256SUMS` verde y **ejecución del binario Linux en
este host (glibc 2.41) con `--health` exit 0**.

## Estado

**Corregido y verificado** (tras la verificación end-to-end del Release; ver la
sección anterior y el resultado anotado al pie).

## Riesgos residuales

- Windows no se ejecuta fuera del runner (sin entorno Windows local); el pin
  reduce el riesgo de migración de sello pero no lo elimina si GitHub retira
  `windows-2022`. Seguimiento: si el runner se deprecia, fijar el siguiente
  Windows GA y revalidar.
- El suelo de glibc 2.35 excluye distros más antiguas (Ubuntu 20.04, Debian 11);
  se documenta en el README en vez de ocultarse.
- DF-C3 (Windows real) permanece como riesgo no verificado.
