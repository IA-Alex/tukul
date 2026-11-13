# Notas de trabajo — A-04 reutilizado

Este archivo **no forma parte del corpus**. Documenta la decisión sobre A-04
y por qué es un reutilizado parcial. No debe entregarse al modelo.

## Origen

`Articulos/publicacion_por_incidente/¿Qué hace que un incidente deje el laboratorio y llegue al dominio público?.md`

Copia **byte a byte** en `A-04.md`. El original no se ha tocado.

## Por qué se reutiliza

- Es prosa redactada en primera persona, en español, sobre un incidente real
  de seguridad con IA. El dominio (IA/seguridad) es distinto del resto.
- Tiene un tono de crónica que encaja con I-04 («añade una conclusión de dos
  frases»): el texto ya acaba con una pregunta, no con una conclusión cerrada.
- Contiene entidades citables: Hugging Face, OpenAI, «modelos de frontera»,
  y una referencia temporal implícita («no recuerdo un caso reciente»).

## Por qué es parcial (limitación declarada)

| Requisito del INFORME para A-04 | Estado |
|---|---|
| 800–1200 palabras | **No.** 181 palabras. |
| Cronología con fechas | **No.** No contiene fechas explícitas. |
| Título (H1) | **No.** El título es texto plano, no encabezado. |
| Estructura de párrafos verificable | **Sí.** 6 párrafos diferenciables. |

**Consecuencia práctica:** A-04 sirve para I-04 (añadir conclusión al final) y
para F-01 (no inventar entidades al editar), pero **no** sirve para I-01
(«acorta un 30 % sin perder datos»): 181 palabras no permiten un recorte del
30 % sin destruir el texto. Para un A-04 completo habría que redactar una
crónica de 800–1200 palabras con fechas.

## Decisión

Se mantiene el reutilizado y se declara la limitación, en lugar de:
- (a) inflar el original (violaría «textos originales intactos»), o
- (b) generar uno nuevo sin decirlo (ocultaría que el corpus no cubre I-04 con
  la extensión que el propio informe exige).

Si el mantenedor prefiere un A-04 nuevo de 800–1200 palabras con cronología,
basta con reemplazar `A-04.md` y actualizar el manifiesto; el verificador
exigirá entonces H1 y ≥ 2 fechas.
