# Política de canales — entregas garantizadas entre worker e interfaz

La aplicación separa el texto en streaming de los eventos de control para que
una ráfaga de fragmentos jamás pueda retrasar ni perder la finalización de una
petición. Hay **dos canales** con garantías distintas a propósito.

## Los dos canales

```
worker threads (LLMSessionManager)
   │  on_chunk(texto)             on_complete/on_error(...)
   ▼                               ▼
ChunkBuffer (lock + lista)    control_queue (queue.Queue, sin tope)
   │  coalesce, no bloquea         │  put_nowait, nunca se pierde
   ▼                               ▼
process_ui_events()  →  _render_pending_chunks()  →  _dispatch_ui_event()
```

### `ChunkBuffer` (texto)

- `tukul_ui/chunk_buffer.py`
- El productor solo toma un lock y añade a una lista: **nunca bloquea y nunca
  descarta**. El consumidor recoge de una vez todo lo pendiente desde su ciclo
  anterior, que es la coalescencia natural bajo congestión.
- No necesita tope propio: el techo de RAM ya lo impone
  `LLMSessionManager._accept_chunk` sobre el total de la respuesta.

### `control_queue` (eventos de ciclo de vida)

- `queue.Queue` **sin límite**, insertada con `put_nowait`.
- Eventos de control (uno por petición, al final):

| Evento | Tupla | Significado |
|--------|-------|-------------|
| `"error"` | `(tipo, request_id, mensaje, files)` | El streaming falló |
| `"complete"` | `(tipo, request_id, resultado, files, usage, request_type)` | El streaming terminó |

- **Nunca se pierden**: una finalización no debe bloquearse detrás de una ráfaga
  de texto, porque dejaría la petición viva con la conexión abierta.

### Ownership y generación

Tkinter es dueño de `control_queue`, `ChunkBuffer`, `streaming_request` y del
estado visual. El worker solo ejecuta `LLMSessionManager` y publica callbacks;
no toca widgets. `TukulApp` usa `generation_counter` como request ID y
`request_types[request_id]` para distinguir `normal` de `review`; no existe una
clase `RequestState` independiente en la implementación actual. Cada request
tiene además su propio `threading.Event` de cancelación.

Una petición cancelada se elimina del mapa, se descartan sus chunks pendientes y
se ignoran callbacks tardíos. Cambiar de documento reemplaza el
`DocumentScope`; el request ID evita que una respuesta antigua aplique al nuevo
artículo. En el cierre, la app marca `closing`, cancela y espera con tope los
workers antes de destruir Tk. Los workers son daemon como red de seguridad; no
son el mecanismo normal de persistencia. Un timeout o excepción del proveedor
se convierte en un evento `error` y se propaga a la UI.

## Consumidor: `process_ui_events()`

Se reprograma con `after(50, ...)` en un `finally`, de modo que un manejador que
falle no deje la aplicación sorda (ninguna respuesta volvería a llegar y el
botón Enviar quedaría deshabilitado para siempre).

1. `_render_pending_chunks()` vuelca el texto acumulado. Los chunks de una
   petición cancelada se descartan; los de una revisión no se pintan (su
   contenido es JSON técnico que solo debe llegar al diálogo de hallazgos).
2. `_dispatch_ui_event()` despacha los eventos de control del ciclo anterior.
3. Reprograma el siguiente ciclo.

Antes de cerrar una petición, `_flush_pending_chunks()` garantiza que ningún
fragmento recibido se pierda por llegar el `complete` en el mismo ciclo que los
últimos chunks.

## Invariantes bajo prueba

- Una finalización nunca se pierde ni bloquea al worker, por larga que sea la
  ráfaga que la preceda.
- Ningún fragmento recibido se pierde: se coalesce, no se descarta.
- El texto pendiente se pinta ANTES de que su finalización cierre la petición.

Estas garantías se ejercitan en `tests/test_cola_eventos.py` con el código de
producción real (`ChunkBuffer`, la cola de control, `process_ui_events()`).
