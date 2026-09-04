# ADR-0002: separar streaming y eventos de control

STATUS: Accepted

## CONTEXT

Los fragmentos de texto pueden llegar en ráfagas. Una cola única podía retrasar la finalización o el error.

## DECISION

`ChunkBuffer` acumula y coalesce texto bajo lock; `control_queue` sin límite entrega `complete` y `error`. La UI drena chunks antes del evento terminal.

## ALTERNATIVES

Una cola única; polling directo del worker desde Tkinter; descartar chunks bajo congestión.

## CONSEQUENCES

La finalización no queda detrás del texto y Tkinter sigue siendo dueño de la UI. El buffer consume memoria hasta el techo de respuesta del cliente.

## SECURITY_IMPACT

Los límites de línea, body y respuesta acotan memoria frente a un proveedor malicioso.

## TESTING_IMPACT

`tests/test_cola_eventos.py`, `test_queue_semantics.py` y tests de regresión verifican orden, cancelación y eventos tardíos.
