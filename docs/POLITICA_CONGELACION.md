# Política de congelación — Tukul `0.6.0`

**Estado:** CONGELADA con descongelación restringida a correcciones.
**Vigente desde:** 2026-11-13.
**Base del dictamen:** `docs/audit/cierre-2026-11-13-final.md` (CERRADO).

## Qué significa «congelada»

Sobre `0.6.0` **solo se acepta una corrección**. Nada más entra en esta rama de
versión: ni funciones nuevas, ni mejoras, ni refactorizaciones, ni cambios de
dependencias por gusto, ni ajustes cosméticos.

La razón es la del dictamen: el contrato se cumple y está verificado sobre el
artefacto distribuido. Cada cambio posterior obliga a repetir la evidencia
(gate, build, firma, verificación en destino) y vuelve a poner en riesgo algo
que hoy está demostrado.

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
  no **incumplidos**. Abren contrato nuevo, no descongelan `0.6.0`.
- Cambios de dependencias no motivados por un defecto o una CVE.

## Procedimiento de descongelación

1. **Declarar el defecto.** Abrir una entrada con: síntoma, pasos de
   reproducción, promesa incumplida (enlace a `docs/` o CHANGELOG), severidad y
   el artefacto afectado.
2. **Confirmar la clasificación.** Si no encaja en las cuatro categorías, no
   descongela: se deriva a contrato nuevo.
3. **Corregir con regresión.** La prueba debe fallar con el código anterior. Si
   no falla, la prueba no demuestra nada.
4. **Gate completo.** `./scripts/quality-gate.sh` en verde.
5. **Publicar parche.** Versión `0.6.x` (nunca reutilizar `0.6.0`), tag nuevo y
   Release firmada.
6. **Verificar en destino.** `sha256sum -c`, `--health`, `cosign verify-blob`
   sobre lo descargado, no sobre lo construido.
7. **Actualizar el dictamen.** Registrar el defecto, la corrección y la nueva
   evidencia; el dictamen sigue siendo CERRADO, con la corrección anotada.

## Reglas que no se negocian

- **Nunca se reescribe un tag publicado.** `0.6.0` queda como está, aunque
  tuviera defectos: los defectos se corrigen en `0.6.x`. Reescribir un tag
  invalida toda firma que alguien haya verificado.
- **Un release firmado no se reemplaza.** Si el artefacto está mal, se publica
  otro y se marca el anterior como retirado, sin borrar la evidencia.
- **Sin `|| true` en firma ni verificación.** Un fallo de firma detiene la
  publicación; nunca se publica «con aviso».

## Qué pasaría con un defecto real encontrado hoy

```text
1. Reproducir y documentar  →  docs/audit/defecto-<fecha>.md
2. Clasificar               →  defecto confirmado / regresión
3. Prueba de regresión      →  falla antes, pasa después
4. Gate                     →  764+ pruebas, 0 omitidas
5. Publicar                  →  v0.6.1 firmada
6. Verificar en destino      →  checksum + health + cosign
```

El único caso que **no** pasa por aquí es la pérdida de datos o un fallo de
seguridad activo: ahí se corrige primero y se documenta inmediatamente después,
sin esperar al gate completo si ello retrasa la mitigación.
