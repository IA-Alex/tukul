# Contribuir a Tukul

Este documento cubre el flujo de trabajo del repositorio. No repite los contratos
técnicos: cada tema enlaza a su fuente canónica en [`docs/`](docs/README.md).

## Preparar el entorno

Requiere Python ≥ 3.11 y las bibliotecas de Tk.

```bash
python -m pip install -e ".[dev,keyring]"
```

En Debian/Ubuntu, `python3-tk` y (para las pruebas de interfaz) `xvfb`.

## Comprobaciones antes de enviar cambios

La puerta única es el quality gate, que replica lo que exige CI:

```bash
./scripts/quality-gate.sh
```

Cubre `ruff`, `mypy`, la instalación aislada, `pytest` con cobertura y Tk bajo
`xvfb`, la ausencia de pruebas omitidas, `pip-audit` y `bandit -lll -ii`.
`tests/test_quality_gate_parity.py` fija que ningún paso de CI desaparezca del
gate. El detalle vive en [`docs/TESTING.md`](docs/TESTING.md).

Una prueba omitida se trata como fallo: una señal verde con omisiones sería
falsa. No añadas `skip` salvo que sea imposible ejercitar el código en CI, y en
ese caso documenta por qué.

## Commits

Se usa [Conventional Commits](https://www.conventionalcommits.org/):

```
tipo(área): descripción breve en imperativo
```

- **Tipos:** `feat`, `fix`, `test`, `docs`, `refactor`, `perf`, `build`, `ci`,
  `chore`.
- **Área:** el módulo o dominio afectado (`ui`, `storage`, `llm`, `revisión`,
  `seguridad`, `auditoría`…). Se escribe en el idioma del proyecto.
- La descripción explica el **porqué** cuando no es obvio; el **qué** ya se ve
  en el diff.

## Ramas y versionado

- La rama de trabajo real es `master`; `main` y `develop` también disparan CI.
- Ramas de trabajo: `tipo/área-corta` (p. ej. `fix/contrato-revision`,
  `ci/validacion-pipeline`).
- **Versionado semántico** (`MAJOR.MINOR.PATCH`) en `pyproject.toml` y tags
  `vX.Y.Z`. Un cambio incompatible sube `MAJOR` y se documenta en el CHANGELOG.
- Los tags `v*.*.*` disparan el build de binarios y el Release; ver
  [`docs/RELEASE.md`](docs/RELEASE.md).

## CHANGELOG

Toda modificación observable (comportamiento, interfaz, contrato) se anota en
[`CHANGELOG.md`](CHANGELOG.md) bajo la versión en curso, agrupada por
*Añadido / Cambiado / Corregido / Eliminado*, con el motivo y, si aplica, el
identificador del hallazgo de auditoría.

## Documentación

Al cambiar comportamiento, actualiza **la fuente primaria y el documento
canónico** en el mismo cambio (regla de autoridad en
[`docs/README.md`](docs/README.md)). Si un documento contradice al código,
prevalece el código y el conflicto se registra como deuda, no se resuelve
copiando historia.

## Auditorías

Los informes fechados viven en [`docs/audit/`](docs/audit/). Los hallazgos se
numeran `DF-NNN` **reiniciando el contador en cada auditoría con fecha**; al
citarlos, incluye siempre la fecha para evitar colisiones entre informes.
