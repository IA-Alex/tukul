# Corte de `0.8.3` — cierre

Sesión del 2026-11-17/18. Skills: `reparador-integral-es` + `arquitecto-asesor`.
Sucede a [`cierre-0.8.2.md`](cierre-0.8.2.md).

## Contenido del corte

`0.8.3` agrupa cinco commits sobre `0.8.2`:

| Commit | Cambio | Tipo |
|---|---|---|
| `771d997` | Un `401`/`403` del proveedor se explica como credencial inválida, no como fallo críptico del eval | Defecto confirmado |
| `f54dc7c` | Retira el transporte Gemini, sin consumidor ni decisión de producto | Defecto confirmado (rama sin defensa) |
| `cc8aeed` | Documenta el 401 y el retiro de Gemini; sube la versión a `0.8.3` | Documentación |
| `d8cf1e7` | búsqueda: cuota de GDELT (429 por IP tras NAT) y EPSS en lote (lista por comas); UI: chip de modelo y ayuda inicial | Defecto confirmado |
| `bfae907` | Retira `_cabe_si_se_recorta` (sin consumidor) y añade el arnés reproducible de C3 | Limpieza + auditoría |

## Verificación

### Gate local (`./scripts/quality-gate.sh`)

`✓ QUALITY GATE PASSED` — **904 passed**, 938 registradas, **0 omitidas**,
cobertura total **87,40 %**. `ruff` y `mypy` limpios.

### CI del commit tageado (`bfae907`, run `44222206831`)

**success** en `test (3.11)`, `test (3.12)`, `test (3.13)` y `security`.

### Release y verificación en destino

Release `v0.8.3` (no draft, no prerelease) con `tukul-linux-x86_64`,
`SHA256SUMS`, `sbom.cdx.json` y `tukul-linux-x86_64.bundle`. Verificado **sobre lo
descargado**:

- `sha256sum -c SHA256SUMS` → **«La suma coincide»**.
- `./tukul-linux-x86_64 --health` → **`versión: Tukul 0.8.3`**.

### Coherencia de versión

`pyproject.toml` = `uv.lock` = `--health` = **`0.8.3`**; tag `v0.8.3` sobre
`bfae907`; `git describe --tags` → **`v0.8.3` limpio**.

## C3 — lector de pantalla

Deja de estar «no verificado»: queda **verificado como no expuesto**. El detalle
y la evidencia están en
[`verificacion-c3-atspi-2026-11-17.md`](verificacion-c3-atspi-2026-11-17.md).
Tk no publica árbol de accesibilidad, así que ningún lector de pantalla puede
leer la app; abrirlo exige una **decisión de arquitectura** (otro toolkit o una
capa AT-SPI propia), no una reparación. Se añade el arnés reproducible
(`scripts/verificar_atspi.py` + `diagnostico_tk_atspi.py` + `control_positivo_atspi.py`),
que no entra en la suite ni en CI (necesita `orca`/`gi` del sistema).

## Estado del dictamen

**CERRADO en lo verificable.** Gate verde, CI verde, versión y tag coherentes,
artefacto verificado en destino. Deuda viva no bloqueante:

- **C3** — límite de plataforma de Tk; abrir contrato nuevo si se quiere
  accesibilidad real.
- **Evals** — el arnés está listo; la credencial del `.env` seguía respondiendo
  `401` en el último intento. Falta una credencial válida para correr las
  baterías promptfoo.
- **H2** (`app.py < 2 300`) — no-defecto declarado (ADR-0005).
