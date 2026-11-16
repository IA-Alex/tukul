# Diagnóstico inicial — evals de Tukul `0.8.0` (supersedido)

> **Supersedido por** [`reparacion-evals-2026-11-16.md`](reparacion-evals-2026-11-16.md).
> Se conserva como registro del punto de partida, **no** como causa raíz. Su
> lectura de la causa `sin_hallazgos` quedó desmentida: ver §Corrección.

**Fecha:** 2026-11-16 · **Skill:** `arquitecto-de-entrega`
**Entregable:** cerrar los evals en verde.
**DoD:** los 5 puntos de `docs/contracts/contratos-0.8.md`.
**Estado inicial:** `HEAD = 6977027` (`v0.7.2-5`), árbol limpio, sin tag `v0.8.0`.

## Evidencia de ejecución

| Ítem | Comando | Resultado |
|---|---|---|
| Eval base sin exportar key | `npx promptfoo eval -c evals/promptfooconfig.yaml` | 0/8, HTTP 401 |
| Eval base con key del `.env` | `set -a; . ./.env; …` | **7/8**, 1 fallo |
| Causa **del adaptador** sobre la respuesta guardada | `diagnose_findings` | `sin_hallazgos`, 0 |
| Respuesta cruda del modelo | mismo prompt, mismo modelo | `{"review": "…", "omitted": null}` — sin `findings` |
| Prueba del criterio real | añadir `findings` al mismo JSON | `ok`, 1 hallazgo |
| Versión del tag | `git describe --tags` | `v0.7.2-5-g6977027` (no `v0.8.0`) |

Antes del diagnóstico se concluyó que el caso fallido también caía en
`categoria.js` (`parse_findings_categories = []`). Eso es descripción, no causa.

## Corrección

El diagnóstico situó la causa en la respuesta del modelo (`{"review": …}`) y en
la supuesta flakiness. Al escribir la prueba de regresión se comprobó que
`diagnose_findings('{"review":"x"}')` devuelve **`esquema_ajeno`**, no
`sin_hallazgos`, y que la causa real del falso verde estaba en el **caso de
artículo limpio**, que no exigía que llegara la revisión. La reparación y su
evidencia están en `reparacion-evals-2026-11-16.md`.
