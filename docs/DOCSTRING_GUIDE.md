# Guía de Docstrings — Estándar Articulador

**Estado:** SUPPORTING, no bloquea el quality gate. La guía conserva prioridad
para APIs públicas y contratos de persistencia, seguridad y concurrencia; no
exige docstrings mecánicos para cada función privada. No se añade enforcement
automático porque el gate actual no obtiene valor suficiente de contar o medir
docstrings.

## Objetivo

Documentar toda función o método público con el formato Google-style. Prioridad:
**lo crítico primero** (flujo de peticiones, persistencia y seguridad).

## Formato (Google-style, tipos Python 3.10+)

### Función simple

```python
def abrir_documento(ruta: Path) -> tuple[bool, str, ArticleSession]:
    """Abre un artículo y lo convierte en sesión.

    Args:
        ruta: Ruta del artículo Markdown a abrir.

    Returns:
        Tupla (éxito, mensaje_de_error, sesión).
    """
```

### Función con errores

```python
def cargar_perfiles(ruta: Path) -> tuple[dict[str, LlmProfile], str]:
    """Carga los perfiles LLM del TOML de forma defensiva.

    Args:
        ruta: Ruta al archivo de configuración.

    Returns:
        (perfiles, perfil_activo). Nunca falla: ante TOML corrupto usa defaults.

    Raises:
        Ninguna por diseño: los perfiles inválidos se ignoran dejando rastro.
    """
```

### Método con estado

```python
def process_ui_events(self) -> None:
    """Consume los eventos de UI publicados por los hilos de trabajo.

    El bombeo se reprograma en `finally` para que un manejador que falle no
    deje la aplicación sorda.
    """
```

## Nombres actuales de los métodos principales

El código ha cambiado de nombres con el tiempo; usar estos (no los antiguos):

| Antes | Ahora |
|-------|-------|
| `send` | `send_message` |
| `_queue_event` | (ya no existe: `ChunkBuffer` + `control_queue`) |
| `partial_output` | (ya no existe: `streaming_text`/`streaming_request`) |
| `ContextOrchestrator` | (ya no existe: contexto explícito de artículos) |

## Checklist por módulo

```
articulador_core/
├── autosave.py           ✓ write_autosave / read_autosave / clear_autosave
├── config_validator.py   ✓ validate_startup_config
├── health.py             ✓ check_health / status_string
├── llm.py                ✓ LLMClient (retries, stream, complete)
├── logging_config.py     ✓ setup_logging / file_logging_status
├── models.py             ✓ LlmProfile / ChatMessage / ArticleSession
├── prompting.py          ✓ build_editor_prompt
├── review.py             ✓ parse_findings
└── storage.py            ✓ atomic_write / load_profiles / save_profiles

articulador_ui/
├── app.py                ✓ ArticuladorApp (request, review, finish, cancel, autosave)
├── chunk_buffer.py       ✓ ChunkBuffer
├── dialogs.py            ✓ show_settings_dialog / show_review_dialog
├── document_manager.py   ✓ DocumentManager
├── document_scope.py     ✓ DocumentScope
├── estado.py             ✓ EstadoUI
├── estilo.py             ✓ sistema visual
├── llm_session_manager.py ✓ LLMSessionManager
└── tooltip.py             ✓ ToolTip
```

## Regla práctica

Un docstring de una línea basta cuando el nombre ya es claro; un docstring de
bloque es obligatorio cuando el método tiene efectos de estado, validación,
concurrencia o errores que el lector no puede deducir del nombre.
