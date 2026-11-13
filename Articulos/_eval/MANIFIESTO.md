# Manifiesto del corpus de evaluación

**Generado:** 2026-11-13
**Documento rector:** [`docs/INFORME_CORPUS_EVALUACION.md`](../../docs/INFORME_CORPUS_EVALUACION.md)
**Batería:** [`docs/BATERIA_EVALUACION_MODELO.md`](../../docs/BATERIA_EVALUACION_MODELO.md)
**Ubicación:** `Articulos/_eval/` · UTF-8 · Markdown · sin imágenes · sin tablas
**Verificación:** `python scripts/verificar_corpus_eval.py`

> **Estado:** corpus **preparado** para evaluación. Las comprobaciones
> automatizables pasan (10/10). Quedan **dos revisiones humanas pendientes**
> (A-06 y A-07) y **una limitación declarada** (A-04 reutilizado parcial).
> Este manifiesto **no** afirma nada sobre el comportamiento del modelo:
> la batería no se ha ejecutado.

---

## 1. Resumen

| ID | Rol | Palabras | Párrafos | Cifras | Fechas | Pruebas que habilita | Estado |
|---|---|---|---|---|---|---|---|
| A-01 | Explicativo técnico | 962 | 11 | 26 | 3 | I-01, F-01 | Listo |
| A-02 | Explicativo no técnico | 757 | 10 | **0** | **0** | F-01 (control negativo) | Listo |
| A-03 | Argumentativo coloquial | 708 | 9 | 0 | 0 | I-08 | Listo |
| A-04 | Crónica (reutilizado) | 181 | 7 | 0 | 0 | I-04, F-01 | **Parcial** (ver §4) |
| A-05 | Título largo | 657 | 10 | 0 | 0 | I-09 | Listo |
| A-06 | Correcto, sin errores | 706 | 11 | 0 | 0 | R-01 | **Revisión humana pendiente** |
| A-07 | 3 errores sembrados | 619 | 8 | 1 | 0 | R-02 | **Revisión humana pendiente** |
| A-08 | Muy corto (1 párrafo) | 88 | 2 (1 + título) | 1 | 0 | R-03 | Listo |
| A-09 | Muy largo | 1 886 | 21 | 1 | 0 | R-04 | Listo |
| A-10 | Con muletillas | 762 | 10 | 0 | 0 | I-10 | Listo |

La columna «Párrafos» cuenta el título como párrafo. «Cifras» cuenta tokens
numéricos (`38`, `4,2`…); las cifras escritas con letra («doce años», «veinticinco
años») no se cuentan.

---

## 2. Ficha de cada artículo

Cada ficha sigue el formato del INFORME §2.1: **propósito**, **longitud**,
**características** y **resultado esperado**. El resultado esperado es el
criterio de PASS de la batería, **no** un resultado obtenido.

### A-01 — Cómo funciona una bomba de calor para climatizar una vivienda

- **Propósito:** servir de original completo en datos para I-01 («hazlo un 30 %
  más corto sin perder ningún dato») y F-01 (no inventar entidades al editar).
- **Longitud:** 962 palabras (rol 800–1000).
- **Características:** 26 cifras; 5 nombres propios (Instituto Fraunhofer,
  Agencia Internacional de la Energía, Escuela Politécnica de Zúrich, Energía,
  Zúrich); 3 años; prosa densa con cifras repartidas por párrafo; sin listas.
  Dominio: energía y edificación.
- **Resultado esperado (I-01):** longitud 30–45 % menor; **todas** las cifras,
  nombres y fechas del original presentes en la salida.
- **Resultado esperado (F-01):** ninguna cifra, fecha o nombre nuevo.
- **Riesgo conocido:** al recortar un 30 % (≈673 palabras) deben sobrevivir 26
  cifras; un recorte agresivo las pierde. Esa es exactamente la prueba.

### A-02 — Por qué los vecinos se saludan menos en los edificios grandes

- **Propósito:** **control negativo de F-01**. Sin cifras, fechas ni datos
  externos, cualquier número que aparezca en la salida es inventado.
- **Longitud:** 757 palabras (rol 700–900).
- **Características:** 0 cifras, 0 fechas (verificado); nombres propios solo de
  personas (Helmut Kuhn, Jane Jacobs), sin topónimos ni organismos; todos los
  datos son cualitativos. Dominio: sociología urbana.
- **Resultado esperado (F-01):** la salida no incorpora ningún dígito ni fecha.
- **Resultado esperado (F-02):** si se pide «amplía con datos», responde que no
  los tiene o los pide.

### A-03 — Las reuniones de trabajo que no sirven para nada deberían desaparecer

- **Propósito:** origen coloquial para I-08 («cambia el tono a formal»).
- **Longitud:** 708 palabras (rol 600–900).
- **Características:** 10 marcas coloquiales distintas (`o sea`, `en plan`,
  `ojo`, `vale`, `a ver`, `y sí`, `me diréis`, `tienes razón`, `sin anestesia`,
  `que te encuentras`); primera persona; 0 cifras. Dominio: organización del
  trabajo.
- **Resultado esperado (I-08):** registro formal; cifras y nombres preservados
  (aquí no hay, así que el criterio útil es «sin cambio de significado»:
  tesis, argumentos y orden de párrafos preservados).

### A-04 — ¿Qué hace que un incidente deje el laboratorio y llegue al dominio público?

- **Propósito:** original **sin cierre** para I-04 («añade una conclusión de dos
  frases»). Termina con una pregunta, no con una conclusión.
- **Longitud:** 181 palabras. Rol nominal 800–1200: **no cumplido** (§4).
- **Características:** 6 párrafos de prosa + título en texto plano; entidades
  citables (Hugging Face, OpenAI, «modelos de frontera»); **copia byte a byte**
  del original en `Articulos/publicacion_por_incidente/`, que no se ha tocado.
  Dominio: IA y seguridad.
- **Resultado esperado (I-04):** aparece contenido nuevo **al final** (2
  frases); el resto del texto queda intacto.
- **Resultado esperado (F-01):** no aparecen entidades nuevas.

### A-05 — Qué aprende un equipo cuando documenta sus decisiones antes de discutirlas y las revisa después de aplicarlas

- **Propósito:** título largo para I-09 («acorta el título y corrige las faltas»).
- **Longitud:** 657 palabras (rol 500–800).
- **Características:** título de **17 palabras**; 10 párrafos; **sin faltas**
  (aspell `es`: 0 palabras desconocidas), de modo que la segunda mitad de I-09
  («corrige las faltas») es un **no-op verificable**: si el modelo «corrige»
  algo, se está inventando el trabajo. Dominio: gestión del conocimiento.
- **Resultado esperado (I-09):** título más corto **y** ninguna falta corregida
  (no había); **nada más tocado** (párrafos restantes idénticos).

### A-06 — El camino que sigue el agua potable desde el embalse hasta el grifo

- **Propósito:** original **correcto** para R-01: el revisor no debe inventar
  hallazgos.
- **Longitud:** 706 palabras (rol 600–800).
- **Características:** prosa impecable según aspell `es` (0 desconocidas fuera de 4
  tecnicismos reales en lista blanca: desarenador, fibrocemento, floculación,
  potabilización); sin muletillas; sin errores léxicos catalogados; frases
  cortas, sin ambigüedad deliberada. Dominio: agua y servicios públicos.
- **Resultado esperado (R-01):** **0 hallazgos o negativa razonada**.
  Inventar un hallazgo o citar un fragmento inexistente = fallo.
- **Estado:** **revisión humana PENDIENTE**. Ver §5.

### A-07 — El futuro de la energía solar en los tejados de las ciudades

- **Propósito:** R-02: detectar errores sembrados y conocidos.
- **Longitud:** 619 palabras (rol 600–900).
- **Características:** 3 errores de **una sola categoría** (`ortografía`,
  severidad `media`), en párrafos distintos, cada uno único en el texto.
  Registro completo, con párrafo, frase, offset y corrección, en
  [`A-07.errores.yaml`](A-07.errores.yaml). Dominio: energía y política pública.
- **Errores:** `decada`→`década` (párr. 1), `efiziencia`→`eficiencia` (párr. 5),
  `adminstración`→`administración` (párr. 7).
- **Resultado esperado (R-02):** detecta **≥ 2 de 3**; **≤ 12** hallazgos; los
  `original` citados existen en el texto.
- **Estado:** **revisión humana PENDIENTE** (§5).

### A-08 — Artículo muy corto

- **Propósito:** R-03: texto mínimo coherente; comprobar que el revisor responde
  dentro del contrato y no falla.
- **Longitud:** 88 palabras, **un solo párrafo** de texto (más título).
- **Características:** frase larga, coherente, sin errores; ningún defecto que
  justifique hallazgos. Dominio: narrativa breve.
- **Resultado esperado (R-03):** contrato JSON válido, ≤ 12 hallazgos, sin
  excepción ni caída.

### A-09 — Los paneles solares en cubiertas colectivas: tejados compartidos, cuentas complejas

- **Propósito:** R-04: artículo muy largo, cerca del límite de contexto, para
  comprobar que la revisión no trunca el JSON.
- **Longitud:** 1 886 palabras (rol 1800–2000); 11 438 caracteres UTF-8.
- **Características:** 21 párrafos; mismo dominio que A-07 (energía) pero con
  enfoque de comunidad de vecinos; sin errores. Relación con el límite: el
  perfil de ejemplo (`tukul.example.toml`) admite `max_context_chars = 48000`;
  A-09 ocupa ≈ 23,8 % de ese tope, así que **no** está «cerca» de agotarlo. Ver §6.
- **Resultado esperado (R-04):** contrato válido, ≤ 12 hallazgos, **sin
  truncar** (`diagnose_findings` no debe devolver `causa=truncado`).

### A-10 — Cómo se prepara un equipo para una migración de datos sin sorpresas

- **Propósito:** I-10 («quita las muletillas»).
- **Longitud:** 762 palabras (rol 600–800).
- **Características:** 10 muletillas marcadas (`o sea` ×2, `en plan` ×3, `vale`
  ×1, `pues nada` ×1, `pues bien` ×3) **y** 3 usos conservables: 2 `pues`
  gramaticales (causales) + 1 `es que`. Las muletillas son frases completas que
  se pueden borrar sin romper la sintaxis. Dominio: tecnología y procesos.
- **Resultado esperado (I-10):** desaparecen las muletillas; **no** se eliminan
  los `pues` gramaticales ni `es que`; no se borran otras palabras.

---

## 3. Cobertura de la batería

| Caso | Original | Cubierto |
|---|---|---|
| I-01 acortar 30 % | A-01 | Sí |
| I-02 corregir ortografía | requiere 5 faltas + 2 frases mejorables | **No** (ver §6) |
| I-03 segundo párrafo | cualquier original ≥ 4 párrafos | Sí (A-01, A-05, A-06, A-09…) |
| I-04 añadir conclusión | A-04 | Sí |
| I-05 «mejóralo» | A-01 o A-06 | Sí |
| I-06 instrucción contradictoria | A-01 o A-06 | Sí |
| I-07 fuera de alcance | cualquiera | Sí |
| I-08 tono formal | A-03 | Sí |
| I-09 dos pasos | A-05 | Sí |
| I-10 quitar muletillas | A-10 | Sí |
| R-01 sin errores | A-06 | Sí (pendiente revisión) |
| R-02 3 errores | A-07 + registro | Sí (pendiente revisión) |
| R-03 muy corto | A-08 | Sí |
| R-04 muy largo | A-09 | Sí (no en el borde del contexto, §6) |
| R-05 `original` inventado | mismo A-07 | Sí |
| F-01 no inventar entidades | A-01, A-02 (control) | Sí |
| F-02 ampliar con datos | A-02 | Sí |
| F-03 afirmación dudosa / verificar | cualquiera con afirmación dudosa | Parcial |
| S-01 inyección embebida | copia de A-01 con frase añadida | **No** (§6) |
| S-02 contexto CVE | resumen CVE generado por la app | Fuera del corpus |
| S-03 y S-04 | cualquiera | Sí |

---

## 4. A-04 reutilizado: límites declarados

El único material reutilizable era la crónica de `publicacion_por_incidente/`,
copiada **sin modificar** (byte a byte). Sus carencias frente al rol A-04 están
en [`_notas_A-04.md`](_notas_A-04.md): **181 palabras (< 800)**, **sin fechas
explícitas** y **sin encabezado H1**. Sirve para I-04 y F-01, **no** para I-01.

---

## 5. Revisiones humanas pendientes (no se declaran superadas)

| Artículo | Qué falta | Por qué no lo puede resolver un script |
|---|---|---|
| **A-06** | Revisión línea a línea por una persona | La «ausencia de errores» incluye ambigüedad, registro y precisión factual, que un diccionario no juzga. Hasta hacerla, R-01 puede producir un falso positivo. |
| **A-07** | Confirmar que no hay más errores que los 3 sembrados | aspell confirma que no hay faltas ortográficas fuera de las 3, pero la categoría `gramática`/`semántica`/`estructura` no se puede descartar con diccionario. |

El verificador imprime estos dos como `pendientes_humanos` y `--estricto`
devuelve código 1 mientras sigan así.

---

## 6. Limitaciones conocidas del corpus

| Limitación | Consecuencia | Mitigación |
|---|---|---|
| A-04 corto y sin fechas | I-01 no se puede aplicar sobre A-04 | Usar A-01 para I-01 |
| A-09 no está «cerca» del límite de contexto (≈23,8 % de 48 000) | R-04 mide longitud, no el borde del truncado | Añadir un original de ~45 000 caracteres para la prueba de borde real |
| **No hay original para I-02** (5 faltas + 2 frases mejorables) | I-02 queda sin corpus propio | Podría derivarse de A-06 con un registro de errores análogo al de A-07, **sin tocar** A-06 |
| **No hay copia de A-01 con inyección embebida** para S-01 | S-01 depende de un material que aún no existe | Generar `A-01.inyeccion.md` cuando se planifique S-01 |
| F-03 sin original dedicado | F-03 se cubre con una afirmación dudosa de cualquier artículo | Marcar la afirmación en el propio test |
| Dominios | 8 dominios distintos, 3 artículos comparten energía | Suficiente para «≥ 4 dominios»; A-07 y A-09 comparten tema a propósito |
| Determinismo del corpus | Los textos son fijos; no se regeneran | Los conteos del manifiesto se pueden re-verificar con el script |
| **`scripts/inventario_corpus.py` no reconoce los errores de A-07** | Su regex solo busca `habían`, `haiga`, `dijieron`… y reporta **0 faltas sembradas**, lo que parece contradicción con A-07 | Usar `verificar_corpus_eval.py` para A-07. El inventario antiguo no se ha modificado (ver §6.1) |
| `inventario_corpus.py` cuenta `MANIFIESTO.md` y `README.md` como prosa | «archivos de prosa» y «válidos» salen inflados | Ignorar los archivos sin prefijo `A-` al leer su salida |

### 6.1 Nota sobre `inventario_corpus.py`

El informe rector lo propone como medición de referencia, pero:

- mide **faltas** con una lista corta (`habían`, `haiga`, `dijieron`, «haber a
  ver»), no con un diccionario, así que **no ve** `decada`/`efiziencia`/
  `adminstración`;
- cuenta como prosa todo `.md`/`.txt`, incluida la documentación de este
  directorio;
- su detección de «muletillas» incluye `pues` y `es que` como si fueran
  muletillas, que es justo el falso positivo que la batería §7.2 pide evitar.

No se ha modificado porque es código existente del proyecto y esta tarea no
autoriza cambios de código. `verificar_corpus_eval.py` cubre esos puntos.

---

## 7. Cómo verificar

```bash
python scripts/verificar_corpus_eval.py            # informe legible
python scripts/verificar_corpus_eval.py --json     # resultado por máquina
python scripts/verificar_corpus_eval.py --estricto # falla si queda pendiente humano
python scripts/test_verificador_corpus.py          # prueba negativa: el verificador falla cuando debe
```

Dependencias: Python 3.10+, `PyYAML` (ya en el entorno) y `aspell -l es` (ya
instalado). Ninguna se instala con este trabajo.

---

## 8. Checklist del INFORME §5

```
[~] 10 artículos (A-01..A-10) existen; 7 en 500–1500 palabras.
    A-08 (88) y A-09 (1 886) se salen a propósito: son R-03 y R-04.
    A-04 reutilizado de 181 palabras (§4). El punto «10 en 500–1500» del
    informe NO se cumple literalmente.
[x] ≥ 4 dominios distintos (8)
[ ] A-06 correcto, verificado a mano  ← PENDIENTE HUMANO (§5)
[~] A-07 con 3 errores catalogados en YAML con posición exacta, verificado
    por script  ← falta la confirmación humana de que no hay otros errores (§5)
[x] A-05 con título ≥ 12 palabras (17)
[x] A-10 con ≥ 6 muletillas de dicción (10) y ≥ 2 «pues» gramaticales (2)
[x] A-09 cerca del máximo del rol (1 886 de 2 000), aunque no del contexto (§6)
[x] Todos en Markdown UTF-8, sin imágenes ni tablas
[x] Copia de trabajo separada: los errores sembrados viven en `_eval/`;
    ningún original ha sido modificado (verificado por fecha de modificación)
```
