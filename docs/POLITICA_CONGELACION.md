# Política de congelación — Tukul `0.7.1`

**Estado:** VALIDADO EN CÓDIGO, PENDIENTE DE PUBLICACIÓN (push + Release).
**Vigente desde:** 2026-11-15 (parche `0.7.1`); contrato abierto el 2026-11-14.
**Base del contrato:** `docs/contracts/contratos-0.7.md`.
**Sucede a:** `0.6.0`/`0.6.1` (dictamen `docs/audit/cierre-2026-11-13-final.md`,
CERRADO). La rama `0.6.x` queda cerrada y no admite más parches: los defectos
nuevos se atienden por este contrato o por uno posterior.

## Qué significa «contrato nuevo»

A diferencia de la congelación de `0.6.0`, `0.7.0` **sí incorpora funciones y
refactorizaciones** (autoindexado, fuentes de IA, extracción de `TukulApp`). La
congelación de `0.6.0` solo aceptaba correcciones; estas capacidades no encajan
en ninguna categoría de corrección, así que abren contrato, no lo descongelan.

El criterio de cierre es el de `docs/contracts/contratos-0.7.md`: capacidades
esenciales (F1–F4) verificadas, refactorización por responsabilidades sin cambio
de comportamiento observable, y correspondencia código ↔ artefacto ↔ versión
(`tag = HEAD`).

## Qué es una corrección (y qué no)

### Se acepta

| Categoría | Definición | Ejemplo real de esta serie |
|---|---|---|
| **Defecto confirmado** | El comportamiento observable no cumple lo ya prometido en `docs/` o en el CHANGELOG | `open_project` mostraba el artículo anterior |
| **Regresión** | Algo que funcionaba antes y dejó de funcionar | El glob de firma firmaba su propio bundle |
| **Fallo de seguridad** | Exposición, ejecución no autorizada, integridad del artefacto | Firma no verificable |
| **Fallo de entrega** | El artefacto publicado no corresponde al código declarado | Tag ≠ HEAD |

Cada candidato necesita los tres: **evidencia del fallo**, **la promesa
incumplida** (dónde se dijo que eso funcionaba) y **una prueba que falle antes y
pase después**.

### No se acepta

- Funciones nuevas o flags nuevas.
- «Ya que estamos»: refactorizar el archivo al tocar una corrección.
- Bajar el objetivo de H2 (2.300 líneas) como excusa: es mejora, no defecto.
- C3 (lector de pantalla) y C4 (cuotas de proveedor): están **no verificados**,
  no **incumplidos**. Abren contrato nuevo, no bloquean `0.7.0`.
- Cambios de dependencias no motivados por un defecto o una CVE.

## Procedimiento de corte de `0.7.x`

1. **Declarar el alcance.** Capacidades esenciales F1–F4 y refactorización
   DF-001/ADR-0005, con criterio de aceptación verificable cada una
   (`docs/contracts/contratos-0.7.md`).
2. **Coherencia de versión.** `pyproject.toml`, `uv.lock` y `--health`
   reportan la versión de la entrega (`0.7.1` desde el parche visual);
   `uv lock --check` limpio.
3. **Gate completo.** `./scripts/quality-gate.sh` en verde (0 omitidas,
   cobertura ≥ 70 %).
4. **Cortar el tag.** Tag anotado de la entrega (`v0.7.1`, que contiene
   `v0.7.0`) sobre el HEAD validado; `git describe --tags` → `v0.7.1` limpio.
   Push/Release es acción externa: se pide confirmación antes.
5. **Verificar en destino.** `sha256sum -c`, `--health`, `cosign verify-blob`
   sobre lo descargado, no sobre lo construido.
6. **Actualizar el dictamen.** Registrar el cierre y la evidencia; el dictamen
   pasa a CERRADO con la deuda viva enumerada.

## Reglas que no se negocian

- **Nunca se reescribe un tag publicado.** `0.6.0` y `0.6.1` quedan como
  están, aunque tuvieran defectos: los defectos nuevos se atienden por contrato
  nuevo. Reescribir un tag invalida toda firma que alguien haya verificado.
- **Un release firmado no se reemplaza.** Si el artefacto está mal, se publica
  otro y se marca el anterior como retirado, sin borrar la evidencia.
- **Sin `|| true` en firma ni verificación.** Un fallo de firma detiene la
  publicación; nunca se publica «con aviso».

## Qué pasaría con un defecto real encontrado hoy

```text
1. Reproducir y documentar  →  docs/audit/defecto-<fecha>.md
2. Clasificar               →  defecto confirmado / regresión
3. Prueba de regresión      →  falla antes, pasa después
4. Gate                     →  827+ pruebas, 0 omitidas
5. Publicar                  →  v0.7.x firmada
6. Verificar en destino      →  checksum + health + cosign
```

El único caso que **no** pasa por aquí es la pérdida de datos o un fallo de
seguridad activo: ahí se corrige primero y se documenta inmediatamente después,
sin esperar al gate completo si ello retrasa la mitigación.
