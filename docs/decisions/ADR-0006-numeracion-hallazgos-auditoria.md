# ADR-0006: numeración de hallazgos de auditoría — una norma, dos series

STATUS: Accepted

## CONTEXT

`CONTRIBUTING.md` (§ Auditorías) fija que los hallazgos se numeran `DF-NNN`
**reiniciando el contador en cada auditoría con fecha**, y que al citarlos se
incluya siempre la fecha «para evitar colisiones entre informes».

La práctica divergió. La serie de informes
`docs/audit/auditoria-conector-*.md` (pasadas del 2026-11-12, 2026-11-13 y
2026-11-18) numeró sus hallazgos como `H-NN`. Al redactar el informe de la
tercera pasada se detectó la tensión: seguir la norma (`DF-NNN`) rompía la
coherencia *dentro* de la misma serie, y mantener `H-NN` incumplía un documento
NORMATIVE. La asimetría no es de contenido sino de etiqueta: los informes
conector ya usan la fecha en el nombre del archivo y en las citas cruzadas.

Antes de este ADR, el repo tenía las dos prácticas a la vez: los informes de UI
/ frontend (`auditoria-2026-11-12.md`, `auditoria-frontend-2026-11-13.md`) usan
`DF-NNN`; la serie conector usa `H-NN`. Las citas cruzadas del `CHANGELOG` y de
los informes suelen apoyarse en la fecha (del encabezado de versión o del propio
nombre del informe) para desambiguar, que es la intención de la norma.

## DECISION

Se conserva **una sola** regla de numeración para hallazgos nuevos —`DF-NNN` con
contador reiniciado por informe— y se reconoce la serie conector histórica como
una excepción cerrada con su propio prefijo:

1. **Hallazgos nuevos: `DF-NNN`.** Todo informe de auditoría fechado a partir de
   este ADR numera `DF-001`, `DF-002`, … reiniciando en cada informe. Es lo que
   ya hacen los informes de UI/frontend y lo que hizo la tercera pasada conector
   (`docs/audit/auditoria-conector-2026-11-18.md`, `DF-001..DF-005`).
2. **Serie conector previa: `H-NN`, sin reescribir.** Los informes
   `auditoria-conector-2026-11-12.md`, `auditoria-conector-2026-11-13.md` y
   `auditoria-conector-proveedor-2026-11-13.md` se quedan como están (son
   `HISTORICAL` según `docs/README.md`). Reescribir sus números sería reescribir
   historia y romper las citas del `CHANGELOG` ya publicado (`0.4.1`, 2026-11-12)
   que los mencionan como `H-01..H-08`.
3. **Cita siempre con la fecha.** Cualquier referencia a un hallazgo —de
   cualquier prefijo— lleva la fecha del informe (p. ej. `DF-004 (2026-11-18)`,
   `H-01 (2026-11-12)`). Esto es lo que neutraliza la colisión entre series y es
   el requisito que `CONTRIBUTING.md` ya expresaba.
4. **Transición documentada.** La tercera pasada conector explica en su §1 que
   su prefijo es `DF-` y que las pasadas anteriores usaron `H-`, para que un
   lector no confunda `H-01 (2026-11-12)` con `DF-001 (2026-11-18)`.

## ALTERNATIVES

- **Migrar TODA la serie conector a `DF-NNN`.** Rechazado: toca informes
  `HISTORICAL` ya cerrados y sus citas en el `CHANGELOG` publicado; el beneficio
  es solo estético y el coste es reescribir historia, que `docs/README.md`
  prohíbe («el conflicto se registra como deuda, no se resuelve copiando
  historia»).
- **Cambiar la norma a `H-NNN`.** Rechazado: `DF-NNN` es la práctica mayoritaria
  (UI/frontend) y ya está escrita en `CONTRIBUTING.md`; cambiarla obligaría a
  renumerar más informes que quedarse con ella.
- **No hacer nada.** Rechazado: deja dos normas vigentes en conflicto silencioso,
  que es precisamente la deuda que este ADR registra.

## CONSEQUENCES

- La norma de `CONTRIBUTING.md` y la práctica vuelven a coincidir: una regla
  (`DF-NNN`) más una excepción histórica explícita y cerrada (`H-NN` para la
  serie conector previa al 2026-11-18).
- No se renombra ni renumerar ningún informe existente; no se toca el
  `CHANGELOG` ya publicado.
- A partir de aquí, un informe conector nuevo numera `DF-NNN`, aunque su serie
  histórica usara `H-NNN`: la fecha en la cita desambigua.
- Deuda registrada: la serie conector previa queda etiquetada con un prefijo que
  no sigue la norma, aceptado como histórico.

## TESTING_IMPACT

Ninguno: es una convención documental, no hay código que probar. La coherencia
del formato del informe se revisa a mano al redactarlo.
