# Historial de cambios

Todas las modificaciones relevantes del proyecto. El formato sigue las
recomendaciones de [Keep a Changelog](https://keepachangelog.com/es-ES/) y el
proyecto se versiona según [Semantic Versioning](https://semver.org/lang/es/).

## [0.3.0] - 2026-08-17

### Añadido

- Estado de interfaz persistente: geometría de ventana, nivel de zoom,
  documentos recientes y conversación se guardan en `estado.json` (junto a
  `config.toml`) y se recuperan al reabrir Articulador. Persistencia atómica,
  igual que el resto del proyecto; nunca falla la carga (JSON corrupto o
  ausente equivale a estado vacío).
- Conversación por documento: cada artículo conserva su propia hebra entre
  reinicios. Cambiar de artículo dentro de la misma sesión abre la
  conversación de ese documento (o una vacía si es nuevo) en vez de arrastrar
  los turnos del anterior.
- Modo foco (`F11`): oculta la barra superior y el pie para dejar solo el
  artículo visible; se restaura sin perder la disposición de paneles.
- Zoom del cuerpo tipográfico (`Ctrl` `+`/`-`/`0`), acotado entre 80 % y 150 %.
- Documentos recientes: submenú en el menú Archivo, con tope de 10 entradas y
  opción de vaciar la lista.
- Tooltips (`articulador_ui/tooltip.py`) en los controles de la barra
  superior, sin dependencias externas.
- Copiar un mensaje individual del historial de conversación desde su menú
  contextual.
- Métrica de palabras seleccionadas junto al total, en el pie del editor.

### Corregido

- El diccionario de conversaciones persistidas se poda a los documentos
  vigentes (en recientes o el activo) en cada guardado de estado, evitando que
  `estado.json` crezca sin límite con cada artículo que se abrió alguna vez.
- Ajustes menores de contraste y jerarquía tipográfica en el sistema visual
  (`estilo.py`), verificados contra WCAG 1.4.11 en las tres capas de fondo.
- `destroy()` espera (con tope) a que terminen los hilos de `review()`/
  `request()` antes de destruir la ventana, evitando que uno arranque tarde
  y sobreviva al cierre.

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
