# Política de Colas - Semántica de Entregas Garantizadas

## Visión General

La aplicación Articulador utiliza **dos colas separadas** para garantizar que eventos críticos del ciclo de vida nunca se pierdan incluso ante congestión de visualización.

```
┌──────────────────────────────────────────────────────────┐
│                   Event Sources                          │
│         (worker threads, LLM streaming, etc.)            │
└────────────────────┬────────────────────────────────────┘
                     │ _queue_event(event)
                     ├─────────────────────┐
                     ▼                     ▼
        ┌────────────────────┐  ┌──────────────────┐
        │  control_queue     │  │  chunk_queue     │
        │  (sin límite)      │  │  (maxsize=500)   │
        │  GARANTIZADO       │  │  COALESCIBLE     │
        └────────────────────┘  └──────────────────┘
                     │                     │
                     │ get_nowait (1º)     │
                     │                     │ get_nowait (2º)
                     ▼                     ▼
        ┌────────────────────────────────────────┐
        │    process_ui_events()                 │
        │  1. Procesar TODA control_queue        │
        │  2. Procesar lote de chunk_queue       │
        │  3. Reprogramar en 50ms                │
        └────────────────────────────────────────┘
```

---

## Control Queue (Entrega Garantizada)

**Propiedades:**
- `maxsize=None` (sin límite)
- Eventos **críticos para el ciclo de vida**
- **NUNCA se pierden**, incluso ante congestión

**Eventos:**
| Evento | Significado | Criticidad |
|--------|-------------|-----------|
| `"complete"` | Streaming terminó exitosamente | 🔴 Crítica |
| `"error"` | Streaming falló tras emitir chunks | 🔴 Crítica |
| `"context_failed"` | Preparación de contexto falló | 🔴 Crítica |
| `"confirm_and_send"` | Usuario confirmó contexto, enviar | 🔴 Crítica |

**Razón:** Sin estos eventos, la UI queda colgada (`request_active=True` permanente), botones deshabilitados, imposible continuar.

---

## Chunk Queue (Coalescible/Descartable)

**Propiedades:**
- `maxsize=500` (acotada)
- Eventos **de visualización únicamente**
- OK descartar si congestión (no rompe lógica)

**Eventos:**
| Evento | Significado | Criticidad |
|--------|-------------|-----------|
| `"chunk"` | Token recibido del proveedor | 🟡 Visualización |

**Razón:** Chunks son redundantes (se coalescen en `pending_chunks`). Ante UI lenta:
- Descartar un chunk → usuario ve respuesta un poco más lenta
- Perder un control event → app crash (dead lock)

---

## Flujo de `process_ui_events()`

```python
def process_ui_events(self):
    # PASO 1: Procesar TODA la control_queue (garantizada)
    while True:  # Sin límite, procesar todos
        event = self.control_queue.get_nowait()
        # Manejar: complete, error, context_failed, confirm_and_send
        # ↑ Nunca se pierden, aunque hayan 1000

    # PASO 2: Procesar un LOTE de chunks (hasta 50 por ciclo)
    for i in range(50):  # Límite, evitar monopolizar UI
        event = self.chunk_queue.get_nowait()
        # Coalescer + stream_chunk()
        # ↑ OK descartar si está llena

    # PASO 3: Reconsumir en 50ms
    self.after(50, self.process_ui_events)
```

**Garantía:** Procesa **todo** control_queue antes de cualquier chunk.
Si hay 1000 chunks esperando pero 1 complete crítica, complete se procesa inmediatamente.

---

## Manejo de Error Tras Streaming

Cuando hay error **después** que chunks ya se emitieron:

1. **Acumular salida parcial** en `process_ui_events()`
   ```python
   self.partial_output[request_id] = acumulated_text
   ```

2. **Enviar event "error" a control_queue** (garantizado)
   ```python
   control_queue.put_nowait(("error", request_id, error_msg, files))
   ```

3. **Procesar chunks pendientes** luego mostrar banner
   ```python
   # En finish()
   if is_error:
       self.history.insert("end", "[INCOMPLETO] Respuesta interrumpida...\n")
       # Guardar partial_output en conversation, NO error_msg
   ```

**Resultado:** Usuario ve:
- ✅ Respuesta parcial (lo que se emitió antes del error)
- ✅ Banner de [INCOMPLETO] (claridad)
- ✅ Separador visual (contexto visual)
- ✓ Historial conserva salida parcial (no el error)

---

## Garantía de Granularidad en Aprobación

Cambio en **cualquiera** de estas dimensiones requiere **nueva confirmación**:

```python
approval_key = (
    self.profile.endpoint,      # ← Cambio requiere reaprobación
    self.profile.provider,      # ← Cambio requiere reaprobación
    tuple(files),              # ← Archivos del contexto
    content_hash               # ← Cambio de contenido requiere reaprobación
)
```

**Ejemplos:**
- Usuario cambia endpoint → nueva aprobación ✓
- Usuario cambia provider → nueva aprobación ✓
- Contenido del artículo cambia → nueva aprobación ✓
- Solo cambian archivos referenciados → nueva aprobación ✓

---

## Límite de RAM vs Límite de Tokens

### ❌ Problema Original
```python
max_response_chars = max_output_tokens * 4  # ← Asumir 4 chars/token
if accumulated_chars > max_response_chars:
    raise LlmError("Respuesta excede límite")
```

**Problemas:**
- Español: más caracteres por token
- Markdown: símbolos toman espacio
- URLs: mucho carácter por token bajo
- Código: caracteres especiales

→ Corta respuestas válidas prematuramente

### ✅ Solución Actual
```python
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # ← 2MB en RAM
if accumulated_bytes > MAX_RESPONSE_BYTES:
    raise LlmError(f"Respuesta excede límite de memoria")
```

**Ventajas:**
- Confiar en **limite del proveedor** (respeta max_output_tokens realmente)
- Aplicar solo **techo de RAM independiente** (seguridad de memoria)
- Válido para cualquier idioma, formato, carácter especial
- 2MB es prudente para la mayoría de devices

---

## Casos de Prueba (Regresión)

Todos los siguientes casos están cubiertos por tests en `tests/test_queue_semantics.py`:

### Caso 1: Cola de chunks llena + complete
```
1. Llenar chunk_queue hasta 500
2. Enviar event "complete" a control_queue
3. Verificar: complete se procesa (control_queue garantizado)
4. Resultado: botones se reactivan, salida se guarda
```

### Caso 2: Cola de chunks llena + error
```
1. Chunks pendientes + cola llena
2. Enviar event "error" a control_queue
3. Verificar: error se procesa, banner visible
4. Resultado: salida parcial conservada, error mostrado
```

### Caso 3: Error tras varios chunks
```
1. Stream 3 chunks exitosamente
2. Falla en chunk 4
3. Verificar: historial tiene salida parcial + banner
4. Resultado: last_response = salida_parcial (no error)
```

### Caso 4: Cambio de contenido/endpoint/proveedor
```
1. Usuario aprueba: (endpoint_1, provider_1, files, hash_1)
2. Cambio: contenido → hash_2
3. Verificar: mismo tupla pero hash diferente
4. Resultado: se pide nueva confirmación
```

### Caso 5: Parser con datos inválidos
```
1. 20 hallazgos → limita a 12 ✓
2. categoría inválida → rechaza ✓
3. severity inválida → rechaza ✓
4. campo vacío → rechaza ✓
5. campo > 500 chars → rechaza ✓
```

---

## Monitoreo y Debugging

### Logs de Dropped Events
```python
logger.debug(f"Chunk queue full, dropping chunk (UI congestion)")
```

→ Si ves esto con frecuencia, la UI es demasiado lenta para el flujo de datos.
→ Aumentar `chunks_per_batch` en `process_ui_events()` o optimizar UI rendering.

### Control Queue Overflow (Nunca debería pasar)
```python
logger.error(f"CRITICAL: Control queue unexpectedly full: {event_type}")
raise RuntimeError(f"Control queue overflow for {event_type}")
```

→ Si ves esto, hay un memory leak o deadlock en `process_ui_events()`.
→ Debugear inmediatamente.

---

## Compatibilidad Hacia Atrás

- ✅ No hay breaking changes en interfaces públicas
- ✅ Parámetro `is_error` en `finish()` tiene default `False`
- ✅ `_queue_event()` es método privado, no API pública
- ✅ `partial_output` es estructura interna, no expuesta

---

## Decisiones de Diseño

**P: ¿Por qué no usar una sola cola con prioridades?**
A: Más simple + observable. Dos colas clarifican la semántica: control NUNCA pierde, chunks SÍ pueden descartarse.

**P: ¿Por qué 2MB para RAM, no 10MB o 100MB?**
A: 2MB es seguro para mobile + desktop. Respuesta típica es <100KB. Respuesta grande son <500KB. Muy pocas necesitan >2MB.

**P: ¿Por qué congesionar chunks y no control?**
A: Control son eventos raros (<1 por segundo). Chunks son frecuentes (100+/seg en streaming). Estrategia: soltar lo frecuente, guardar lo raro.

---

## Véase También

- [`app.py:_queue_event()`](../articulador_ui/app.py#L119) - Enrutamiento de eventos
- [`app.py:process_ui_events()`](../articulador_ui/app.py#L480) - Consumidor de colas
- [`app.py:finish()`](../articulador_ui/app.py#L421) - Finalización de streaming
- [`tests/test_queue_semantics.py`](../tests/test_queue_semantics.py) - Suite de regresión
