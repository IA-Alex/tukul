# Guía de Docstrings - Estándar Articulador

## Objetivo
90%+ cobertura de funciones públicas. Prioridad: **críticas primero**.

## Formato (Google-style con tipos Python 3.10+)

### Función simple
```python
def send_request(query: str) -> dict[str, Any]:
    """Envía query al LLM y retorna respuesta.

    Args:
        query: Pregunta o solicitud del usuario

    Returns:
        Dict con claves 'response', 'tokens', 'error' (si aplica)
    """
```

### Función con errores
```python
def load_config(path: Path) -> LlmProfile:
    """Carga y valida configuración de LLM.

    Args:
        path: Ruta al JSON de configuración

    Returns:
        LlmProfile validado

    Raises:
        FileNotFoundError: Si archivo no existe
        ValueError: Si configuración es inválida
    """
```

### Método con state
```python
def process_ui_events(self) -> None:
    """Consume eventos de colas con prioridad (control > chunks).

    Procesa:
    1. TODA control_queue (garantizada)
    2. Lote de chunks (coalescible, descartable)

    Llamado cada 50ms desde after() para UI responsiva.
    """
```

## Prioridad: Funciones Críticas Primero

### CRÍTICAS (documentar AHORA):
- `ArticuladorApp.__init__` ✓ DONE
- `ArticuladorApp.process_ui_events` ✓ DONE
- `ArticuladorApp.finish` ✓ DONE
- `ArticuladorApp.send` ✓ DONE
- `ArticuladorApp.review` ✓ DONE
- `ArticuladorApp.stream_chunk` ✓ DONE
- `ArticuladorApp.cancel_request` ✓ DONE
- `ArticuladorApp.request`
- `LLMSessionManager.stream_response`
- `parse_findings`

### IMPORTANTES (después):
- `DocumentManager` métodos
- `ContextOrchestrator` métodos
- Storage functions

### NICE-TO-HAVE:
- Helpers privados (_text, _theme, etc)
- Properties

## Checklist para Alcanzar 90%

```
ArticuladorApp
├── __init__                    ✓
├── process_ui_events           ✓
├── finish                      ✓
├── send                        ✓
├── review                      ✓
├── stream_chunk                ✓
├── cancel_request              ✓
├── request                     ⏳
├── context_failed              ⏳
├── confirm_and_send            ⏳
└── [otros métodos]             ⏳

LLMSessionManager
├── stream_response             ⏳
└── cancel                      ⏳

review.py
├── parse_findings              ⏳

DocumentManager
├── [métodos principales]       ⏳
```

## Ejecución Rápida

Para alcanzar 90%+ rápidamente, agregar docstrings a:
1. Todas las funciones públicas (15-20 min)
2. Métodos principais de clases (20-30 min)
3. Funciones críticas con detalles (30-40 min)

Total: ~2 horas para 90%+
