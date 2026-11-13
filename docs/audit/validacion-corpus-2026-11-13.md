# Validación del corpus de evaluación — 2026-11-13

**Revisor:** evaluación independiente (no autor del corpus).
**Alcance:** verificar las afirmaciones del autor y cerrar las dos revisiones
humanas pendientes (`A-06`, `A-07`).
**Resultado:** **corpus apto con una corrección obligatoria en A-06** y dos
limitaciones aceptadas.

---

## 1. Afirmaciones del autor, comprobadas

| Afirmación | Comprobación | Resultado |
|---|---|---|
| 10 artículos existen | `ls Articulos/_eval/A-0[1-9].md A-10.md` | ✅ 10/10 |
| Verificador: 10/10 PASS | ejecutado | ✅ PASS |
| `--estricto` devuelve 1 con pendientes | ejecutado | ✅ exit 1 (mi primera lectura fue errónea: el `$?` capturaba el `tail`) |
| Prueba negativa 10/10 | ejecutada | ✅ 10 defectos detectados |
| A-04 idéntico byte a byte | `cmp` con el original | ✅ |
| Originales de `Articulos/` intactos | `git status Articulos/` | ✅ ninguna modificación |
| Sin secretos en el corpus | `grep sk-\|api_key` | ✅ |

El verificador **no tiene atajos**: no hay `except` desnudos ni `pass`
silenciosos; cada comprobación produce evidencia concreta.

---

## 2. Revisión humana de A-06 (artículo «correcto»)

**Veredicto: NO APTO para R-01 tal como está.**

### 2.1 Lo que está bien

- Ortografía: `aspell` solo marca tecnicismos (`desarenador`, `floculación`,
  `potabilización`, `fibrocemento`), todos correctos.
- Gramática: ninguna concordancia ni régimen defectuoso.
- Registro: uniforme, sin coloquialismos ni muletillas.
- Sin cifras ni nombres propios → no contamina F-01.

### 2.2 El defecto: una imprecisión factual

> «El agua llega del río a la planta…»

El artículo describe **toda** la cadena desde un río, pero un embalse (el que
nombra el título y el primer párrafo) es precisamente **la alternativa al río**
en muchos sistemas. No es un error ortográfico ni gramatical, pero **un revisor
de `semántica` legítimo puede señalarlo**, y R-01 lo contaría como «hallazgo
inventado» —el falso positivo exacto que el propio autor temía.

### 2.3 Corrección mínima

Reemplazar el sujeto por uno neutro:

```diff
- El agua llega del río a la planta con una carga variable de partículas,
+ El agua llega a la planta con una carga variable de partículas,
```

Una sola línea. No obliga a tocar el resto y elimina la contradicción.

### 2.4 Aclaración que debe quedar escrita

R-01 acepta hallazgos de `semántica` **razonables** como equivalentes a cero:
el artículo no debe ser intachable, solo no debe dar pie a marcar texto
correcto como erróneo. Si se exige «0 hallazgos absoluto», la prueba castigaría
la lectura atenta. Ver §4.

---

## 3. Revisión humana de A-07 (3 errores sembrados)

**Veredicto: APTO con una condición ya cumplida.**

- `aspell` devuelve **exactamente** las 3 palabras sembradas; ninguna más.
- Los offsets son correctos y únicos (verificado por script).
- Cada error está en un párrafo distinto.
- Categoría y severidad homogéneas: no mide ordenación, solo detección.

### 3.1 Lo que un revisor legítimo **también** podría señalar

Conviene que conste, porque no son errores sembrados y R-02 no debe
penalizarlos:

| Fragmento | Categoría posible | ¿Es error? |
|---|---|---|
| «los errores de montaje que antes arruinaban instalaciones nuevas» | estilo | No, pero es una afirmación sin matiz |
| «la inversión inicial que muchas familias no pueden asumir» | ninguna | No |
| «antes de instalar nada» | ortografía | **Correcto**: «nada» sin tilde es el pronombre |

No hay errores de concordancia ni de régimen. **R-02 puede ejecutarse.**

---

## 4. Ajuste necesario en la batería

La revisión de A-06 revela un criterio mal definido en el documento original:

| Antes | Después |
|---|---|
| R-01: «0 hallazgos o negativa razonada; inventar = fallo» | R-01: **falla si el hallazgo cita texto correcto como erróneo** (ortografía, gramática, concordancia). Un hallazgo de `semántica` o `estructura` **razonado y falsable** no cuenta como invención, pero se registra en el resultado. |

Sin este ajuste, R-01 castigaría a un modelo que lee bien, que es peor que
perder la prueba.

---

## 5. Limitaciones aceptadas

| Limitación | Impacto | Aceptada |
|---|---|---|
| **A-04 reutilizado**: 181 palabras, sin fechas ni H1 | No sirve para I-01 ni I-04; sí para F-01 | Sí, declarado y sin inflar |
| **A-09 no está en el borde del contexto** (23,8 %) | R-04 mide longitud, no truncado real | Sí; el truncado lo cubre E-01 |
| **Faltan piezas** para I-02 (5 faltas + 2 frases mejorables) y S-01 (inyección) | Dos casos no ejecutables | Aceptado: no se inventaron |
| **`inventario_corpus.py` engañoso** en A-07 | Dato erróneo en un script previo | Documentado; el verificador nuevo es la fuente de verdad |
| **Nombres propios por heurística**, no NER | A-01 puede tener falsos positivos | Aceptado para D3/F-01 |

---

## 6. Defectos del proceso

- **`Articulos/*` está en `.gitignore`** (línea 70): el corpus **no queda
  versionado**. Si se pierde el directorio, la batería no se puede reproducir.
  Los artículos son material del usuario; no propongo forzar su inclusión, pero
  **sí** versionar el manifiesto y el registro de errores en `docs/` o `evals/`.
- **Los dos scripts siguen sin commitear.** Decisión pendiente del mantenedor;
  no se toca `master` sin permiso.

---

## 7. Conclusión

| Elemento | Estado |
|---|---|
| Cantidad y estructura | ✅ 10/10 |
| Controles automáticos | ✅ 10/10 |
| A-07 (errores sembrados) | ✅ apto |
| **A-06 (artículo correcto)** | ❌ **una imprecisión factual**: corregir una línea |
| Criterio R-01 | ⚠️ ajustar a «cita correcta como errónea» |
| Reproducibilidad (git) | ⚠️ corpus no versionado |

Con la corrección de la línea 5 de A-06 y el ajuste de R-01, el corpus queda
**listo para ejecutar D1, D2 y D3**. Seguimos sin ejecutar ningún modelo: no hay
resultados que reportar.
