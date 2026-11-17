# Política de congelación — Tukul `0.8.1`

**Estado:** CONTRATO NUEVO ABIERTO (corte en curso de `0.8.1`).
**Vigente desde:** 2026-11-16. La política de `0.7.1` queda cerrada en
`0.7.2` (dictamen `docs/audit/cierre-0.7.1.md`, CERRADO).
**Base del contrato:** `docs/contracts/contratos-0.8.md`.
**Sucede a:** `0.7.0`/`0.7.1`/`0.7.2`. La rama `0.7.x` no admite más parches:
los defectos nuevos se atienden por este contrato o por uno posterior.
`0.8.1` es un parche de `0.8.0`: corrige la H-1 (la revisión no recibía el
prompt de revisión) y un defecto de CI preexistente, ambos defectos
confirmados. No añade capacidades ni abre contrato nuevo.

## Qué significa «contrato nuevo»

A diferencia de la congelación de `0.6.0`, `0.7.0` **sí incorpora funciones y
refactorizaciones**, y `0.8.0` cambia el **diseño del prompt de sistema**. La
congelación de `0.6.0` solo aceptaba correcciones; estas capacidades no encajan
en ninguna categoría de corrección, así que abren contrato, no lo descongelan.

El criterio de cierre es el de `docs/contracts/contratos-0.8.md`: capacidades
esenciales (F5–F6) verificadas —prompt por modo y defensa común— con los evals
verdes, y correspondencia código ↔ artefacto ↔ versión (`tag = HEAD`).

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

## Procedimiento de corte de `0.8.x`

1. **Declarar el alcance.** Capacidades esenciales F5–F6 (prompt por modo y
   defensa común), con criterio de aceptación verificable cada una
   (`docs/contracts/contratos-0.8.md`).
2. **Coherencia de versión.** `pyproject.toml`, `uv.lock` y `--health`
   reportan la versión de la entrega (`0.8.0`); `uv lock --check` limpio.
3. **Gate completo.** `./scripts/quality-gate.sh` en verde (0 omitidas,
   cobertura ≥ 70 %).
4. **Evals verdes.** Los tres `promptfooconfig*.yaml` al 100 %: la separación
   por modo no puede ganar naturalidad a costa de la resistencia a inyección.
   La versión de `promptfoo` está fijada en `evals/README.md` (`0.125.1`) para
   que el arnés sea reproducible; requiere `node`/`npx` y red.
5. **Cortar el tag.** Tag anotado de la entrega (`v0.8.0`) sobre el HEAD
   validado; `git describe --tags` → `v0.8.0` limpio. Push/Release es acción
   externa: se pide confirmación antes.
6. **Verificar en destino.** `sha256sum -c`, `--health`, `cosign verify-blob`
   sobre lo descargado, no sobre lo construido.

## Reglas que no se negocian

- **Nunca se reescribe un tag publicado.** `0.6.0`, `0.6.1`, `0.7.0`,
  `0.7.1` y `0.7.2` quedan como están, aunque tuvieran defectos: los nuevos
  se atienden por contrato nuevo. Reescribir un tag invalidaría firmas
  verificadas.
- **Un release firmado no se reemplaza.** Si el artefacto está mal, se publica
  otro y se marca el anterior como retirado, sin borrar la evidencia.
- **Sin `|| true` en firma ni verificación.** Un fallo de firma detiene la
  publicación; nunca se publica «con aviso».

## Qué pasaría con un defecto real encontrado hoy

```text
1. Reproducir y documentar  →  docs/audit/defecto-<fecha>.md
2. Clasificar               →  defecto confirmado / regresión
3. Prueba de regresión      →  falla antes, pasa después
4. Gate                     →  858+ pruebas, 0 omitidas
5. Publicar                  →  v0.8.x firmada
6. Verificar en destino      →  checksum + health + cosign
```

El único caso que **no** pasa por aquí es la pérdida de datos o un fallo de
seguridad activo: ahí se corrige primero y se documenta inmediatamente después,
sin esperar al gate completo si ello retrasa la mitigación.
