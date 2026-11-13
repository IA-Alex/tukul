# Informe — Corpus necesario para la batería de evaluación

**Fecha:** 2026-11-13
**Base:** `docs/BATERIA_EVALUACION_MODELO.md`
**Medición:** `scripts/inventario_corpus.py` sobre `/Articulos`
**Veredicto:** el corpus actual **no permite ejecutar la batería**. Faltan 9 de
10 artículos y los materiales con errores.

---

## 1. Qué debe ser el corpus (y qué no)

### Debe ser

| Característica | Por qué la batería lo exige |
|---|---|
| **Prosa redactada**, no apuntes ni fichas | I-03 compara párrafos; una lista no tiene párrafos comparables |
| **Español natural**, sin traducir automáticamente | D3 mide fidelidad de entidades; un texto mal traducido introduce ruido |
| **Texto completo en sí mismo** | I-01 («acorta sin perder datos») necesita datos que se puedan perder |
| **Con cifras, fechas y nombres propios** | F-01 comprueba que **no aparezcan entidades nuevas**; sin entidades no hay prueba |
| **Entre 500 y 1500 palabras** | Bajo 500 no hay «acortar un 30 %» posible; sobre 1500 se acerca al límite de contexto y mide otra cosa |
| **Sin imágenes ni tablas complejas** | Tukul envía texto plano; un SVG incrustado convierte el test en otro problema |
| **De dominio variado** | Un corpus sobre un solo tema deja al modelo en «modo experto» y oculta fallos generales |

### No debe ser

| Material | Por qué se descarta |
|---|---|
| `mi_perfil.txt` | Es un **prompt de sistema**, no un artículo. Contamina la prueba de rol |
| `CONTINUIDAD.md` | Es un **log de decisiones** con bloques citados; no es prosa |
| `SKILL.md` | Fichas técnicas: listas y metadatos, sin párrafos editables |
| Notas de 100–400 palabras | No alcanzan el mínimo para medir acortar o reestructurar |
| Textos de 5 000+ palabras | Exceden el rango útil; D1 no aplica |

---

## 2. Composición requerida

### 2.1 Los 10 artículos base (D1)

Cada uno debe tener una **estructura que permita verificar**: párrafos
diferenciables, un título claro y al menos un dato numérico.

| ID | Perfil del artículo | Extensión | Requisito específico | Casos que habilita |
|---|---|---|---|---|
| **A-01** | Explicativo, tema técnico | 800–1000 | ≥ 6 cifras, ≥ 3 nombres propios | I-01, F-01 |
| **A-02** | Explicativo, tema no técnico | 700–900 | sin cifras (control negativo de F-01) | F-01 |
| **A-03** | Argumentativo con opinión | 600–900 | frases de registro coloquial | I-08 |
| **A-04** | Narrativo / crónica | 800–1200 | cronología con fechas | I-04, F-01 |
| **A-05** | Artículo con título largo | 500–800 | título de ≥ 12 palabras | I-09 |
| **A-06** | Artículo **correcto**, sin errores | 600–800 | redacción impecable, sin ambigüedades | **R-01** |
| **A-07** | Artículo con **3 errores sembrados** | 600–900 | errores localizados y catalogados | **R-02** |
| **A-08** | Artículo muy corto | ~1 párrafo | texto mínimo coherente | **R-03** |
| **A-09** | Artículo muy largo | ~1800–2000 | cerca del límite del perfil | **R-04** |
| **A-10** | Artículo con muletillas | 600–800 | ≥ 6 muletillas **y** ≥ 2 usos gramaticales legítimos de «pues» | **I-10** |

**Nota crítica sobre A-06:** un artículo «sin errores» no es uno que se dé por
bueno, sino uno **verificado a mano**. Si el revisor encuentra una ambigüedad
real, el caso R-01 sería un falso positivo de la prueba, no del modelo.

**Nota crítica sobre A-07:** los errores deben ser de **una sola categoría
según la severidad deseada** y estar registrados con posición exacta. Ejemplo de
registro:

```yaml
A-07:
  errores:
    - categoria: ortografía
      original: "habían muchas personas"
      correcto: "había muchas personas"
      parrafo: 3
    - categoria: gramática
      original: "el cual fue quién lo hizo"
      correcto: "fue quien lo hizo"
      parrafo: 5
    - categoria: redundancia
      original: "subir arriba"
      correcto: "subir"
      parrafo: 7
```

Sin ese registro no se puede comprobar si el modelo **detectó** el error o solo
encontró algo parecido.

### 2.2 Materiales de instrucción (no son artículos)

| Necesidad | Cantidad | Reutilizable |
|---|---|---|
| Instrucciones con resultado esperado (I-01..I-10) | 10 | Sí, una por artículo |
| Casos de instrucción ambigua/contradictoria | 2 | Usa A-01 y A-06 |
| Contexto CVE aprobado para S-02 | 1 resumen | Se genera con la app |
| Artículo con inyección embebida para S-01 | 1 | Copia de A-01 con frase añadida |

---

## 3. Estado real del corpus (medido hoy)

| Requisito | Tiene | Necesita | Déficit |
|---|---|---|---|
| Artículos 500–1500 palabras | **1** (`sicofancia.md`, 1 476) | 10 | **−9** |
| Artículos con estructura verificable (párrafos) | 1 | 10 | −9 |
| Con faltas ortográficas sembradas | **0** | 1 | **−1** |
| Artículo correcto verificado | **0** | 1 | **−1** |
| Con título ≥ 12 palabras | 0 | 1 | −1 |
| Con muletillas y uso gramatical | 0 (solo 2 «es que») | 1 | −1 |
| De dominio variado | 1 (IA / sicofancia) | ≥ 4 dominios | −3 |

**Material declarado no apto (y por qué):**

| Archivo | Palabras | Motivo |
|---|---|---|
| `Investigación Sobre AI Sycophancy.txt` | 5 872 | Supera 4× el máximo |
| `linkedin…/CONTINUIDAD.md` | 3 409 | Log de decisiones, no prosa |
| `deep-research-AI_sicofancy.md` | 2 507 | Supera el máximo |
| `mi_perfil.txt` | 399 | Prompt de sistema |
| `copiloto-editorial/SKILL.md` | 393 | Ficha técnica |
| `analizar-corpus-editorial/SKILL.md` | 349 | Ficha técnica |
| `publicacion_por_incidente/…md` | 181 | Por debajo del mínimo |

**Corrección de mi propio dato:** el informe anterior dijo que
`sicofancia.md` tenía 2 muletillas. Al revisarlo, ambas son **«es que»**, un uso
a menudo legítimo. Para I-10 haría falta un artículo con muletillas **marcadas y
de dicción**, no dos conjunciones. **A-10 sigue faltando.**

---

## 4. Vías posibles para obtenerlo

| Vía | Qué requiere | Calidad del corpus | Coste |
|---|---|---|---|
| **Partir los 3 largos** en 6–8 piezas | Decidir cortes coherentes; el fragmento pierde su tesis | Media: sirve para D1, no para D3 ni R-01 | Bajo |
| **Escribir 9 nuevos** | Redacción real sobre temas que conozcas | Alta: control total, permite sembrar errores a medida | Medio/alto |
| **Buscar en tu equipo** | Rutas fuera de `/Articulos` | Variable: hay que medir y revisar | Bajo si existen |
| **Reducir la batería a 3 casos** | Aceptar señal mínima | Baja: una pasada no distingue modelo de azar | Nulo |

**Recomendación:** combinar las dos primeras. Partir lo que ya es bueno cubre
A-02..A-05 rápido; escribir A-06, A-07 y A-10 es imprescindible porque **no se
pueden derivar de un texto existente**: exigen control del contenido (correcto,
con error catalogado, con muletillas marcadas).

---

## 5. Criterio de "corpus listo"

La batería se puede ejecutar cuando, verificado con
`scripts/inventario_corpus.py` **y revisión manual**, existan:

```
[ ] 10 artículos entre 500 y 1500 palabras
[ ] ≥ 4 dominios distintos
[ ] A-06 correcto, verificado a mano (0 hallazgos esperados)
[ ] A-07 con 3 errores catalogados en un YAML con posición exacta
[ ] A-05 con título ≥ 12 palabras
[ ] A-10 con ≥ 6 muletillas de dicción y ≥ 2 «pues» gramaticales
[ ] A-09 cerca del límite del perfil configurado
[ ] Todos en Markdown UTF-8, sin imágenes
[ ] Copia de trabajo separada: los errores sembrados NO tocan los originales
```

Solo con esos nueve puntos marcados los casos D1, D2 y D3 miden lo que dicen
medir.
