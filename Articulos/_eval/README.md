# Corpus de evaluación (`Articulos/_eval/`)

Diez artículos diseñados para habilitar los casos de
[`docs/BATERIA_EVALUACION_MODELO.md`](../../docs/BATERIA_EVALUACION_MODELO.md),
conforme a [`docs/INFORME_CORPUS_EVALUACION.md`](../../docs/INFORME_CORPUS_EVALUACION.md).

| Archivo | Qué es |
|---|---|
| `A-01.md` … `A-10.md` | Los artículos, uno por rol |
| `A-07.errores.yaml` | Registro de los 3 errores sembrados (párrafo, frase, offset, corrección) |
| `A-04.origen.sha256` | Hash del original de A-04 (no versionado), para verificar la copia sin depender de él |
| `MANIFIESTO.md` | Propósito, longitud, características y resultado esperado de cada artículo |
| `_notas_A-04.md` | Por qué A-04 es un reutilizado parcial |

## Verificar

```bash
python scripts/verificar_corpus_eval.py            # informe legible
python scripts/verificar_corpus_eval.py --json     # resultado por máquina
python scripts/verificar_corpus_eval.py --estricto # falla si queda pendiente humano
python scripts/test_verificador_corpus.py          # comprueba que el verificador falla cuando debe
```

El verificador **no** llama a ningún modelo, **no** ejecuta Yachay y **no**
escribe en el corpus.

## Estado

- Automático: **10/10 artículos PASS** (verificado 2026-11-13).
- Pendiente humano: revisión de **A-06** y confirmación de **A-07**.
- Limitaciones: ver `MANIFIESTO.md` §4 y §6.

No se debe citar este corpus como evidencia de que el modelo pasa la batería:
la batería **no se ha ejecutado**.
