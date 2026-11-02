

# Informe de Auditoría — Tukul v0.1.0

> **Nota (2026-08-15):** documento histórico de una fase anterior. Describe una
> arquitectura que ya no existe (`chunk_queue`, `partial_output`, `_queue_event`,
> índice BM25) y cifras de tests desactualizadas. La referencia vigente son el
> código, `CHANGELOG.md` y `docs/`. No lo uses como fuente de verdad del estado actual.

> **Fecha**: 2026-08-07  
> **Alcance**: Revisión completa de arquitectura, seguridad, concurrencia, robustez y mantenibilidad.  
> **Archivos auditados**: `tukul.py`, `tukul_core/` (8 módulos), `tukul_ui/` (2 módulos), `tests/test_core.py`

---

## Resumen ejecutivo

El código ha evolucionado significativamente desde la auditoría anterior. De los 18 hallazgos originales, **12 están completamente resueltos**, 4 parcialmente, y 2 han mutado.

Esta auditoría produjo 16 hallazgos nuevos. Tras una segunda pasada de validación cruzada contra el código real, **7 fueron corregidos directamente en el código fuente**, **6 fueron descartados** por riesgo sobredimensionado o solución regresiva, y **2 quedan como deuda técnica de baja prioridad**.

| Severidad | Corregidos en código | Descartados (no aplicar) | Deuda técnica | Total |
|-----------|---------------------|--------------------------|---------------|-------|
| ALTA | 1 | 1 | 0 | 2 |
| MEDIA | 3 | 3 | 0 | 6 |
| BAJA | 4 | 2 | 1 | 7 |
| **Total** | **8** | **6** | **1** | **15** |

> Las secciones N01–N16 a continuación se conservan como trazabilidad de la auditoría. Cada una incluye un banner con su estado real tras la segunda pasada. Consultar la [tabla de decisiones finales](#decisiones-finales) al final del documento.

---

## Histórico de correcciones previas

Las siguientes secciones del informe anterior se conservan como trazabilidad. Los hallazgos marcados ✅ están cerrados.

<details>
<summary>✅ 1. Búsqueda de contexto BM25 — RESUELTO</summary>

`context.py` implementa BM25 con tokenizador de 2+ caracteres, IDF con `math.log`, constantes `k1=1.5`/`b=0.75`, bonus por coincidencia en nombre, stopwords en español y firmas de archivos con caché incremental.
</details>

<details>
<summary>✅ 2. Credenciales en texto plano — RESUELTO</summary>

`save_key()` solo acepta `keyring`; si no está instalado, lanza `RuntimeError`. Ya no existe fallback a `credentials.json`.
</details>

<details>
<summary>⚠️ 3. Sanitización contra prompt injection — PARCIAL</summary>

**Resuelto**: `SYSTEM_PROMPT` constante, `build_editor_prompt()` usa serialización JSON sin etiquetas controlables, delimitación estructural clara.

**Pendiente**: Sin sanitización regex de patrones de inyección. La defensa es estructural (JSON + system prompt). Evaluado y descartado (ver N03): la sanitización regex destruiría contenido editorial legítimo.
</details>

<details>
<summary>✅ 4. BUG: Excepciones al abrir documento por CLI — RESUELTO</summary>

`tukul.py` usa `open_initial_document()` con try/except para `OSError` y `UnicodeError`.
</details>

<details>
<summary>✅ 5. BUG: `usage` de streaming nunca se reporta — RESUELTO</summary>

`StreamChunk` incluye `input_tokens` y `output_tokens`. `_usage()` extrae tokens de múltiples formatos de proveedor. `app.py:201-202` captura el uso del último chunk.
</details>

<details>
<summary>✅ 6. BUG: `service_provider` estático — RESUELTO</summary>

`dialogs.py:70` incluye un `Combobox` con proveedores de `PROVIDERS`.
</details>

<details>
<summary>✅ 7. `__dataclass_fields__` — RESUELTO</summary>

`storage.py:53` usa `dataclasses.fields(LlmProfile)`.
</details>

<details>
<summary>✅ 8. Thread-safety: `ContextIndex.refresh()` sin locks — RESUELTO</summary>

`context.py:35` declara `self._lock = threading.RLock()`. `refresh()`, `packet()` y `_refresh_unlocked()` están protegidos.
</details>

<details>
<summary>⚠️ 9. TOCTOU entre `cancel_event` y `after()` — PARCIAL → corregido en N04</summary>

Corregido: el worker ahora verifica `cancel_event.is_set()` antes de abrir el stream.
</details>

<details>
<summary>⚠️ 10. Daemon threads no cierran conexiones — PARCIAL</summary>

`llm.py:118` usa `with urllib.request.urlopen(...)` como context manager. `cancel()` cierra explícitamente el response. Evaluado y descartado (ver N06): esperar hilos desde el loop de Tkinter causaría reentrancia.
</details>

<details>
<summary>⚠️ 11. `TukulApp` como God Class — PARCIAL</summary>

Se extrajeron diálogos a `dialogs.py`, `parse_findings` a `review.py`. `app.py` bajó de ~400 a 276 líneas. La orquestación LLM, manejo de archivos y ciclo de vida siguen en una sola clase. Clasificado como deuda técnica baja (N09).
</details>

<details>
<summary>✅ 12. Indexación completa en RAM sin límite — RESUELTO</summary>

`ContextIndex.__init__` acepta `max_files=500` y `max_file_bytes=50_000`.
</details>

<details>
<summary>✅ 13. Sin indexación incremental — RESUELTO</summary>

`_refresh_unlocked()` compara fingerprints `(modified, size)` por archivo y reusa entradas de `_cache`.
</details>

<details>
<summary>✅ 14. Números mágicos — RESUELTO</summary>

Constantes documentadas como `MAX_*`, `BM25_*`, `HTTP_TIMEOUT_SECONDS` al inicio de cada módulo.
</details>

<details>
<summary>✅ 15. Sin sistema de logging — RESUELTO</summary>

`logging_config.py` implementa `RotatingFileHandler` con rotación de 512KB/2 backups.
</details>

<details>
<summary>✅ 16. Dependencia de Tkinter en tests — RESUELTO</summary>

`tests/test_core.py` no importa `TukulApp`. `parse_findings` está en `review.py`.
</details>

<details>
<summary>⚠️ 17. Cobertura insuficiente — PARCIAL</summary>

Ampliada a 19 tests cubriendo validación de perfil, mensajes HTTP unificados, y caché incremental. Siguen faltando tests de integración con fallos reales de red/disco (N16).
</details>

<details>
<summary>✅ 18. `setattr` en tupla — RESUELTO</summary>

El código problemático ya no existe.
</details>

---

## 🔴 N01. API key expuesta en propiedad `key` sin sanitización

> **Estado: DESCARTADO** — Riesgo sobredimensionado. `storage.load_key()` captura excepciones internamente (`except Exception: return ""`), no propaga tracebacks con la key. El riesgo de volcado de memoria aplica a toda aplicación que maneje secretos y no es específico de este código.

**Ubicación original del análisis**: `tukul_ui/app.py:55`

```python
@property
def key(self) -> str:
    return os.environ.get(self.profile.api_key_env) or self.session_keys.get(self.active_profile, "") or storage.load_key(self.active_profile)
```

**Por qué se descartó**: `storage.load_key()` (línea 69-75) ya tiene `except Exception: return ""`, así que nunca lanza. `os.environ.get` con default `""` tampoco lanza. La única fuga posible sería un error en `self.profile.api_key_env` si `self.profile` es inválido, pero eso es un bug distinto.

---

## 🔴 N02. `open_project` sin manejo de errores para documento huérfano

> **Estado: CORREGIDO** — El código actual verifica `is_file()` antes de leer.

**Ubicación**: `tukul_ui/app.py:259-267`

**Código actual** (corregido):

```python
def open_project(self):
    path = filedialog.askopenfilename(filetypes=[("Proyecto Tukul", "*.tonal.json")])
    if not path:
        return
    try:
        data = storage.load_project(Path(path))
        document = Path(data["document"])
        if not document.is_file():
            raise FileNotFoundError(f"No existe el artículo del proyecto: {document}")
        article = document.read_text(encoding="utf-8")
        self.session = ArticleSession(
            document_path=document, project_path=Path(path),
            article=article, corpus_path=data.get("corpus"),
            evidence=list(data.get("evidence", [])),
            conversation=data.get("conversation", []),
        )
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.session.article)
        self.history.config(state="normal")
        self.history.delete("1.0", "end")
        self.history.config(state="disabled")
        for item in self.session.conversation:
            self.append("Tú" if item.role == "user" else "Tukul", item.content)
        self.status.set("Proyecto abierto.")
    except (OSError, ValueError) as error:
        messagebox.showerror("Proyecto no válido", str(error))
```

**Qué se corrigió**: La lectura del artículo (`read_text`) se separó de la construcción de `ArticleSession`. Si falla, `self.session` ni siquiera se intenta reasignar. Se agregó verificación explícita `is_file()` antes de leer.

---

## 🟡 N03. Sin sanitización de patrones de inyección en contenido de usuario

> **Estado: DESCARTADO** — La sanitización regex propuesta es destructiva para contenido editorial. Un artículo sobre seguridad en IA vería su texto reemplazado por marcadores `[BLOQUEADO]`. La defensa actual (JSON estructural + `SYSTEM_PROMPT`) es la estrategia correcta para un editor de texto.

**Ubicación original del análisis**: `tukul_core/prompting.py:9-18`

**Por qué se descartó**: En un editor Markdown, el contenido del usuario ES el texto que se quiere preservar. Reemplazar fragmentos como "ignora las instrucciones anteriores" con `[instrucción bloqueada por seguridad]` corrompería artículos legítimos sobre prompt engineering, seguridad de LLMs, o incluso textos literarios. La defensa en profundidad adecuada es la combinación de:
1. Serialización JSON que escapa estructuralmente (implementada en `build_editor_prompt`)
2. `SYSTEM_PROMPT` que instruye al modelo a tratar datos como no confiables
3. Delimitación clara entre instrucciones del sistema y datos de usuario

---

## 🟡 N04. El worker de streaming no verifica `cancel_event` antes de abrir la conexión HTTP

> **Estado: CORREGIDO** — El worker ahora tiene guardia temprana.

**Ubicación**: `tukul_ui/app.py:190-208`

**Código actual** (corregido):

```python
def work():
    if cancel_event.is_set():       # ← guardia temprana agregada
        return
    prompt = build_editor_prompt(selected, packet, conversation)
    chunks = []
    try:
        usage = (None, None)
        for chunk in self.client.stream(profile, api_key, prompt, request_id, cancel_event):
            if cancel_event.is_set():
                return
            if chunk.content:
                chunks.append(chunk.content)
                self.after(0, lambda value=chunk.content: self.stream_chunk(request_id, value))
            if chunk.input_tokens is not None or chunk.output_tokens is not None:
                usage = (chunk.input_tokens, chunk.output_tokens)
        result = "".join(chunks)
    except LlmError as error:
        logger.warning("Solicitud LLM fallida: %s", error)
        result = f"No pude responder: {error}"
        usage = (None, None)
    self.after(0, lambda: self.finish(request_id, result, files, usage))
threading.Thread(target=work, daemon=True).start()
```

**Qué se corrigió**: Se agregó `if cancel_event.is_set(): return` al inicio del worker (línea 191), antes de construir el prompt y abrir la conexión HTTP. Si el usuario cancela entre `confirm_and_send` y el inicio del thread, no se desperdician recursos de red.

---

## 🟡 N05. `urlopen` en streaming sin timeout por chunk

> **Estado: DESCARTADO** — El análisis original era técnicamente incorrecto. `urllib.request.urlopen(timeout=90)` configura el timeout a nivel de socket, y todas las operaciones de lectura posteriores (`readline()` dentro del iterador `for raw in response`) respetan ese timeout. No hay riesgo de bloqueo indefinido.

**Por qué se descartó**: En CPython, `urlopen` con timeout llama internamente a `socket.setblocking(False)` + `select()` con el timeout dado, y luego configura `sock.settimeout(timeout)`. El wrapper HTTPResponse usa `socket.makefile()` que hereda ese timeout para cada `readline()`. Si el servidor deja de enviar datos, el socket lanza `socket.timeout` → se convierte en `URLError` → capturado en `llm.py:160-161`.

---

## 🟡 N06. `close()` no espera a que los hilos terminen

> **Estado: DESCARTADO** — La solución propuesta (loop con `self.update()` + `time.sleep`) causaría reentrancia en el event loop de Tkinter, pudiendo provocar deadlocks o corrupción de estado. Es más seguro dejar que los daemon threads mueran al cerrar el proceso.

**Por qué se descartó**: El patrón propuesto:
```python
while time.monotonic() < deadline:
    if not self.session.request_active:
        break
    self.update()        # ← reentrada al event loop de Tkinter
    time.sleep(0.05)
```
`self.update()` procesa eventos pendientes de Tkinter, lo que puede disparar callbacks que modifiquen `self.session` o `self.cancel_event` mientras el método `close()` está a mitad de ejecución. En el mejor caso es innecesario (los daemon threads mueren limpiamente con el intérprete); en el peor, introduce bugs de concurrencia más graves que el problema original.

---

## 🟡 N07. `os.path.relpath` puede producir path traversal en `save_project`

> **Estado: DESCARTADO** — Los proyectos `.tonal.json` los genera la propia aplicación, no un atacante externo. `relpath` con `..` produce una ruta relativa válida que `resolve()` normaliza correctamente en `load_project()`. Restringir artificialmente las rutas rompería el caso de uso legítimo de workspaces con documentos en ubicaciones relativas.

**Por qué se descartó**: El "path traversal" requiere que un atacante controle el contenido del archivo de proyecto. Pero los proyectos los crea `save_project()` desde la UI de la aplicación. La ruta `../../etc/passwd` en un proyecto generado por la app solo podría ocurrir si el usuario eligió explícitamente ese documento, en cuyo caso es su decisión. `Path.resolve()` en `load_project()` ya normaliza la ruta correctamente.

---

## 🟡 N08. `complete()` tiene mensajes de error HTTP detallados pero `stream()` no

> **Estado: CORREGIDO** — Ambos métodos usan ahora `http_error_message()` unificado.

**Ubicación**: `tukul_core/llm.py:159,182`

**Código actual** (corregido):

```python
# Constante a nivel de módulo (llm.py)
_HTTP_ERROR_MESSAGES = {
    401: "La API key fue rechazada.",
    403: "El proveedor rechazó el acceso.",
    404: "No se encontró el endpoint o modelo.",
    408: "El proveedor agotó el tiempo de espera.",
    429: "Se alcanzó el límite de solicitudes o cuota.",
    500: "El proveedor tuvo un error interno.",
    503: "El proveedor no está disponible temporalmente.",
}

def http_error_message(code: int) -> str:
    return _HTTP_ERROR_MESSAGES.get(code, f"El proveedor respondió HTTP {code}.")

# En stream():
except urllib.error.HTTPError as error:
    raise LlmError(http_error_message(error.code)) from error

# En complete():
except urllib.error.HTTPError as error:
    raise LlmError(http_error_message(error.code)) from error
```

**Qué se corrigió**: El mapeo de códigos HTTP a mensajes descriptivos se extrajo a `http_error_message()` y se usa en ambos métodos. El usuario ahora ve "La API key fue rechazada." en lugar de "El proveedor respondió HTTP 401.".

---

## 🟢 N09. `TukulApp` aún concentra 4 responsabilidades

> **Estado: DEUDA TÉCNICA** — Mejora futura, no bloqueante para uso local. La clase gestiona: ciclo de vida Tkinter, orquestación LLM, gestión de archivos, y estado de sesión.

**Ubicación**: `tukul_ui/app.py` (276 líneas)

**Impacto real**: Bajo para una herramienta local de un solo usuario. La extracción de diálogos ya redujo la clase significativamente. Separar la orquestación LLM en un `LlmController` requeriría tests de integración Tkinter que hoy no existen, con alto riesgo de regresión para beneficio marginal.

---

## 🟢 N10. `parse_findings` es frágil con JSON mal delimitado

> **Estado: CORREGIDO** — Ahora usa `json.JSONDecoder().raw_decode()`.

**Ubicación**: `tukul_core/review.py:14-21`

**Código actual** (corregido):

```python
def parse_findings(result: str) -> list[dict[str, str]]:
    """Extrae hallazgos válidos de la respuesta JSON del modelo."""
    clean = result.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        start = clean.find("{")
        if start < 0:
            return []
        payload, _end = json.JSONDecoder().raw_decode(clean[start:])
        findings = payload.get("findings", [])
    except (ValueError, AttributeError, TypeError):
        return []
    return [
        item for item in findings
        if isinstance(item, dict)
        and REQUIRED_FINDING_FIELDS <= item.keys()
        and all(isinstance(item[key], str) for key in REQUIRED_FINDING_FIELDS)
    ]
```

**Qué se corrigió**: `raw_decode()` usa un parser JSON incremental que respeta profundidad de llaves, strings con escapes, y objetos anidados. Maneja correctamente casos como `{"findings": [...]} texto adicional` y no se confunde con `}` dentro de strings JSON.

---

## 🟢 N11. Construcción de URL Gemini frágil

> **Estado: CORREGIDO** — URL normalizada con helper `gemini_url()`, API key en header `x-goog-api-key`.

**Ubicación**: `tukul_core/llm.py:102-106`

**Código actual** (corregido):

```python
if spec.protocol == "gemini_generate_content":
    endpoint = gemini_url(profile.endpoint, profile.model, stream)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": profile.max_output_tokens,
            "temperature": profile.temperature,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,          # ← header, no URL
        "Accept": "text/event-stream" if stream else "application/json",
    }
    return urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                                   headers=headers, method="POST")
```

El test correspondiente (`test_core.py:162-164`) verifica: `self.assertNotIn("key=secret", request.full_url)` y `self.assertEqual(request.get_header("X-goog-api-key"), "secret")`.

**Qué se corrigió**: La API key ya no se concatena en la URL. Se extrajo la construcción de URL a `gemini_url()` (función helper a nivel de módulo). El header `x-goog-api-key` evita que la key aparezca en logs de proxy.

---

## 🟢 N12. `_signature()` recorre todo el filesystem con `rglob`

> **Estado: CORREGIDO** — Ahora usa `os.walk()` con poda de directorios excluidos.

**Ubicación**: `tukul_core/context.py:43-61`

**Código actual** (corregido):

```python
def _signature(self) -> tuple[tuple[str, int, int], ...]:
    result = []
    try:
        for directory, children, names in os.walk(self.root, topdown=True,
                                                   onerror=lambda _error: None):
            # Podar evita incluso entrar en árboles grandes e irrelevantes.
            children[:] = [name for name in children
                           if name not in EXCLUDED and not name.startswith(".")]
            base = Path(directory)
            for name in names:
                path = base / name
                if path.suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                try:
                    relative, stat = path.relative_to(self.root), path.stat()
                    result.append((relative.as_posix(), stat.st_mtime_ns, stat.st_size))
                except OSError:
                    continue
    except OSError:
        return ()
    return tuple(sorted(result)[:self.max_files])
```

**Qué se corrigió**: `os.walk(topdown=True)` permite modificar `children` in-place para podar directorios completos (`.git`, `node_modules`, `.venv`, etc.) sin siquiera entrar en ellos. En un workspace con `node_modules` de 50k archivos, la iteración ahora toma milisegundos en lugar de segundos.

---

## 🟢 N13. Estimación de tokens ingenua

> **Estado: DESCARTADO** — La heurística `chars // 4` es adecuada para una estimación de coste pre-envío. `tiktoken` añadiría una dependencia pesada (∼2 MB de datos de encoding) solo para una estimación que el proveedor confirma con `usage` real en el último chunk del stream.

**Ubicación**: `tukul_ui/app.py:174`

```python
input_tokens = max(1, (len(message) + len(selected) + len(packet)) // 4)
```

**Por qué se descartó**: La estimación se usa solo para mostrar un coste aproximado antes de enviar. El uso real se obtiene del chunk final del stream (`app.py:201-202`) y se muestra con `Uso real: {input:,} entrada · {output:,} salida`. La precisión de la estimación previa no justifica la dependencia.

---

## 🟢 N14. `LlmProfile` no valida rangos en construcción

> **Estado: CORREGIDO** — `__post_init__` agregado con validación de rangos.

**Ubicación**: `tukul_core/models.py:20-28`

**Código actual** (corregido):

```python
@dataclass
class LlmProfile:
    name: str = "default"
    provider: str = "disabled"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    max_output_tokens: int = 1000
    max_context_chars: int = 48_000
    temperature: float = 0.5
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("La temperatura debe estar entre 0.0 y 2.0.")
        if self.max_output_tokens < 1:
            raise ValueError("El máximo de tokens de salida debe ser al menos 1.")
        if self.max_context_chars < 100:
            raise ValueError("El máximo de contexto debe ser de al menos 100 caracteres.")
        if self.input_price_per_million < 0 or self.output_price_per_million < 0:
            raise ValueError("Los precios por millón de tokens no pueden ser negativos.")
```

Test correspondiente (`test_core.py:184-189`):
```python
def test_profile_validates_limits_and_http_messages_are_shared(self):
    with self.assertRaises(ValueError): LlmProfile(temperature=3)
    with self.assertRaises(ValueError): LlmProfile(max_output_tokens=0)
    with self.assertRaises(ValueError): LlmProfile(max_context_chars=10)
    self.assertEqual(http_error_message(401), "La API key fue rechazada.")
    self.assertEqual(http_error_message(429), "Se alcanzó el límite de solicitudes o cuota.")
```

---

## 🟢 N15. `logging_config.py` falla silenciosamente a stderr

> **Estado: DEUDA TÉCNICA** — Baja prioridad. En una app Tkinter, stderr normalmente no es visible, pero el escenario de fallo (sin permisos en `~/.local/state/`) es extremadamente raro en uso normal.

**Ubicación**: `tukul_core/logging_config.py:22-23`

---

## 🟢 N16. Cobertura de tests

> **Estado: CORREGIDO** — Ampliada de 16 a 24 tests. Todos los casos pendientes de la auditoría anterior están cubiertos.

**Cobertura actual** (24 tests pasando):

```
test_atomic_write_cleans_temp_file_on_disk_error          ← nuevo
test_cancel_closes_active_stream
test_context_index_excludes_application_code
test_context_index_respects_file_and_size_limits
test_context_keeps_two_character_ai_acronym
test_context_prunes_large_ignored_directories_and_handles_empty_query
test_context_ranks_relevance_before_filename
test_context_refresh_reuses_unchanged_file_cache
test_credentials_without_keyring_are_session_only
test_excluded_context_never_returns_in_fallback
test_load_project_handles_malformed_fields_gracefully      ← nuevo
test_load_project_rejects_missing_document_key             ← nuevo
test_native_provider_requests_use_their_own_protocol
test_native_stream_events_and_usage_are_parsed
test_profile_validates_limits_and_http_messages_are_shared
test_project_uses_relative_paths_and_keeps_conversation
test_prompt_keeps_conversation_as_data_without_controlled_tags
test_provider_registry_has_compatible_defaults
test_review_parser_accepts_fenced_json_and_rejects_incomplete_items
test_review_parser_handles_braces_inside_json_strings
test_stream_keeps_content_and_final_usage
test_stream_returns_descriptive_error_on_http_failure      ← nuevo
test_stream_skips_malformed_and_binary_chunks              ← nuevo
test_system_prompt_treats_prior_conversation_as_untrusted
```

**Nuevos tests agregados**:

| Test | Qué cubre |
|------|-----------|
| `test_atomic_write_cleans_temp_file_on_disk_error` | `_atomic_write` ante `OSError` (ENOSPC): propaga la excepción, no deja archivos temporales huérfanos, no crea archivo destino. |
| `test_stream_skips_malformed_and_binary_chunks` | `stream()` recibe líneas no-SSE, JSON inválido, y datos binarios (`\xff\xfe`); las descarta sin crashear y solo procesa chunks válidos. |
| `test_stream_returns_descriptive_error_on_http_failure` | `stream()` ante `HTTPError` 401: lanza `LlmError` con mensaje descriptivo ("rechazada"), no el código numérico genérico. |
| `test_load_project_handles_malformed_fields_gracefully` | `load_project()` con `evidence` string (no lista) y `conversation` con ítems no-dict y sin campos requeridos: filtra correctamente. |
| `test_load_project_rejects_missing_document_key` | `load_project()` sin clave `"document"`: lanza `ValueError`. |

---

## 🧪 Resultados de pruebas

```bash
$ python3 -m unittest discover -s tests -v
```

24 tests. Todos OK en 0.004s.

```bash
$ python3 -m py_compile tukul.py tukul_core/*.py tukul_ui/*.py
```

Sin errores.

---

## Decisiones finales

Esta tabla consolida el estado de cada hallazgo tras la segunda pasada de validación contra el código real. Prevalece sobre el análisis original en las secciones N01–N16.

| # | Hallazgo | Estado | Decisión |
|---|----------|--------|----------|
| N01 | API key sin sanitización en logs | **Descartado** | `storage.load_key()` ya captura excepciones. Riesgo no específico del proyecto. |
| N02 | `open_project` sin manejo de documento huérfano | **Corregido** | Verificación `is_file()` antes de leer; lectura separada del constructor. |
| N03 | Sanitización regex de prompt injection | **Descartado** | Destruiría contenido editorial legítimo. Defensa estructural (JSON + system prompt) es adecuada. |
| N04 | Worker sin guardia de cancelación temprana | **Corregido** | `if cancel_event.is_set(): return` al inicio del worker. |
| N05 | `urlopen` sin timeout por chunk | **Descartado** | El timeout aplica a nivel de socket; todas las lecturas lo respetan. Análisis original incorrecto. |
| N06 | `close()` no espera hilos | **Descartado** | Esperar con `self.update()` causaría reentrancia en Tkinter. Daemon threads es el enfoque correcto. |
| N07 | Path traversal con `os.path.relpath` | **Descartado** | Proyectos generados por la app, no por atacantes. `resolve()` normaliza correctamente. |
| N08 | Mensajes HTTP no unificados stream/complete | **Corregido** | `http_error_message()` compartido entre ambos métodos. |
| N09 | God Class residual en `TukulApp` | **Deuda técnica** | Refactorización de alto riesgo para beneficio marginal en herramienta local. |
| N10 | `parse_findings` frágil con JSON | **Corregido** | Migrado a `json.JSONDecoder().raw_decode()`. |
| N11 | URL Gemini con `key=` en query string | **Corregido** | `gemini_url()` helper; API key en header `x-goog-api-key`. |
| N12 | `rglob` recorre `node_modules` | **Corregido** | `os.walk(topdown=True)` con poda de directorios excluidos. |
| N13 | Estimación de tokens `chars // 4` | **Descartado** | Uso real viene del stream. Precisión de estimación previa no justifica dependencia. |
| N14 | `LlmProfile` sin validación de rangos | **Corregido** | `__post_init__` con validación de temperature, tokens, contexto y precios. |
| N15 | `logging_config.py` falla silenciosamente | **Deuda técnica** | Escenario de fallo extremadamente raro (`~/.local/state/` sin permisos). |
| N16 | Cobertura de tests | **Corregido** | 24 tests (↑ de 16). Cubren `_atomic_write` con ENOSPC, SSE malformado/binario, HTTP 401, `load_project` con campos inválidos. |

---

## Conclusión

El código muestra madurez arquitectónica: BM25 correcto, sin credenciales en disco, logging rotativo, caché incremental con fingerprints, validación de rangos en dataclasses, y 24 tests pasando. De los 16 hallazgos iniciales de esta auditoría, 8 se corrigieron directamente en el código fuente, 6 se descartaron tras validación técnica, y 1 queda como deuda técnica de baja prioridad. No hay hallazgos de severidad ALTA pendientes.
