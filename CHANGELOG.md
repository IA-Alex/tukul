# Historial de cambios

Todas las modificaciones relevantes del proyecto. El formato sigue las
recomendaciones de [Keep a Changelog](https://keepachangelog.com/es-ES/).

## [0.2.1] - 2026-08-15

### Añadido

- Reintentos con backoff en `LLMClient` ante errores transitorios (408, 429,
  5xx) y fallos de conexión, respetando la cabecera `Retry-After`. Se reintenta
  solo la apertura de la conexión, nunca a mitad de un stream.
- Autosave y recuperación ante cierres abruptos: el artículo sin guardar se
  respalda en `~/.local/state/articulador/autosave/` y se ofrece restaurarlo al
  reabrir el documento.
- Tope de tamaño en la apertura de artículos (5 MB) para no agotar la RAM.
- Cobertura medida y exigida en el pipeline (mínimo 70 %).

### Eliminado

- El índice BM25 y el orquestador de contexto automático
  (`articulador_core/context.py`, `articulador_ui/context_orchestrator.py`),
  que quedaron sin uso al pasar a contexto explícito de artículos.
- La bandera `--workspace` de la CLI, sin efecto desde aquel cambio.
- `scripts/lint.sh`, absorbido por `scripts/quality-gate.sh`.

### Corregido

- `storage._atomic_write` pasa a ser `storage.atomic_write` (API pública usada
  por `DocumentManager`).
- Cancelación unificada en un único `_cancel_active_request`; antes había dos
  copias que ya divergían.
- La barra de aprobación de contexto se oculta al cancelar la petición.
- `DocumentManager.open_project` captura ahora `UnicodeError` en la lectura.

## [0.2.0] - 2026-08-12

- Interfaz visual "Articulator" (sistema de capas, estados explícitos).
- Diálogo de revisión estructurado; el prompt técnico y el JSON no llegan al
  historial ni a la conversación.
- `DocumentScope`: estado derivado del documento, reemplazado en bloque.
- Canal de chunks (`ChunkBuffer`) separado de la cola de control garantizada.
- Pipeline de CI (ruff, mypy, pytest bajo X, diagnóstico `--health`).
