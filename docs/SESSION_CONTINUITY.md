# Continuidad de Sesión — Tukul

> Última actualización: 29/9/2026
> Rama: `master` — Commit `3d9a92f`

## Estado actual

Se completaron:
- **Fase 1**: Fundación del módulo `real_time_feed` y analizador de impacto
- **Fase 1b**: Simplificación de proveedores LLM (solo DeepInfra + Novita AI)
- **Renombre**: `Articulador` → `Tukul` (paquetes, clases, rutas, metadata)
- **Fase 2 (completa)**: Refactor completo de `threat_feed.py` como wrapper sobre los 5 adaptadores (NVD, EPSS, KEV, MITRE ATT&CK, arXiv). Todos los adaptadores comparten el mismo patrón de red: urllib puro, NO_REDIRECT_OPENER, timeout fijo, reintentos con backoff exponencial, jitter aleatorio (0-25%) y techo de bytes. `build_threat_context()` ahora acepta `include_mitre` y `include_arxiv` como parámetros opcionales. La API pública existente se mantiene intacta.
- **Fase 2 (UI)**: Integración del botón "Generar sugerencia de impacto…" en el diálogo `manage_references`. Pipeline completo: `FeedOrchestrator.fetch_all()` → `FoggEngine.analyze()` → `ConflictDetector.detect()` → `SuggestionGenerator.generate()` → `PostValidator.validate()`. Resultados como `ContextArticle` con autorización automática.

---

## Lo que se implementó

### Modelos (`tukul_core/models.py`)
- `FeedSource`, `FeedEntry`, `FoggAnalysis`, `SourceConflict`, `ConsumerSuggestion`
- Todas `@dataclass(frozen=True)`

### Paquete `tukul_core/real_time_feed/`
| Archivo | Propósito |
|---|---|
| `__init__.py` | Exporta `FeedCache`, `FeedNormalizer`, `FeedOrchestrator` |
| `cache.py` | `FeedCache` — persistencia JSON con TTL y escritura atómica |
| `normalizer.py` | `FeedNormalizer` — deduplicación, orden por severidad, enriquecimiento NVD+EPSS+KEV, filtrado |
| `orchestrator.py` | `FeedOrchestrator` — fetch paralelo con threads, cache check, degradación granular |
| `adapters/__init__.py` | `REGISTRY` que mapea IDs de fuente a clases adaptadoras |
| `adapters/base.py` | `SourceAdapter` (ABC) con contrato `fetch()` + `normalize()` |
| `adapters/nvd.py` | NVD API v2 |
| `adapters/epss.py` | FIRST EPSS |
| `adapters/kev.py` | CISA KEV |
| `adapters/mitre_attack.py` | MITRE ATT&CK Enterprise (STIX vía GitHub CTI) |
| `adapters/arxiv.py` | arXiv API (cs.CR + cs.AI) |

### `tukul_core/threat_feed.py` (wrapper de compatibilidad)
- **`build_threat_context()`** — orquesta NVD + EPSS + KEV + opcionalmente MITRE ATT&CK y arXiv
- **`fetch_nvd_recent()`, `fetch_epss()`, `fetch_kev()`** — wrappers para fuentes CVE
- **`fetch_mitre_attack()`, `fetch_arxiv()`** — nuevos wrappers para fuentes no-CVE
- Parámetros opcionales keyword-only: `include_mitre=False`, `include_arxiv=False`
- Manejo de degradación: si MITRE o arXiv fallan, se anota en el packet sin bloquear el resto del contexto
- `ThreatFeedEntry` (CVE normalizado con CVSS + EPSS + KEV)
- `ThreatFeedError`, `NvdError`, `EpssError`, `KevError`, `ResponseTooLargeError`

### Analizador de impacto (`tukul_core/impact_analyzer.py`)
- `FoggEngine` — evalúa Motivación + Habilidad + Desencadenantes (Fogg Behavior Model)
- `ConflictDetector` — detecta contradicciones NVD vs EPSS vs KEV por CVE ID
- `SuggestionGenerator` — construye prompt estructurado para LLM, parsea respuesta a `ConsumerSuggestion`
- `PostValidator` — verifica sin psicofancia, validaciones vacías, incoherencias, impacto/audiencia válidos

### Proveedores LLM (`tukul_core/llm.py`)
- Eliminados 5 proveedores: deepseek, openrouter, ollama, anthropic, gemini
- Agregado **Novita AI** (`novita`) a `PROVIDERS` con endpoint `https://api.novita.ai/v3/openai/chat/completions`
- **DeepInfra** y **Novita AI** — ambos usan protocolo OpenAI Chat Completions, sin lógica adaptadora por proveedor
- Sistema de prompt y parsing SSE unificado (OpenAI-compatible)

### Renombre completo: Articulador → Tukul
- Paquetes: `articulador_core/` → `tukul_core/`, `articulador_ui/` → `tukul_ui/`
- Entry point: `articulador.py` → `tukul.py`, comando `articulador` → `tonal`
- Clase principal: `ArticuladorApp` → `TukulApp`
- Display name: `"Articulador"` → `"Tukul"` (título, burbujas, status, system prompt)
- User-Agent HTTP: `Articulador/ThreatFeed` → `Tukul/ThreatFeed`
- Rutas de sistema: `~/.config/articulador/` → `~/.config/tukul/`, `~/.local/state/articulador/` → `~/.local/state/tukul/`
- Logger: `"articulador"` → `"tonal"`
- Keyring: `"articulador"` → `"tonal"`
- Extensión archivos: `*.articulador.json` → `*.tonal.json`
- Package PyPI: `articulador` → `tonal`
- GitHub CI/CD: todos los paths y asset names actualizados

### Documentación
- `docs/decisions/ADR-0003-real-time-query-and-impact-suggestions.md` — ADR aceptado
- `docs/CONFIGURATION.md` — actualizado con providers novita/deepinfra y paths Tukul
- `docs/archive/IMPLEMENTATION_SUMMARY.md` — actualizado con nota del refactor de adaptadores (2026-09-28)
- `docs/SESSION_CONTINUITY.md` — esta misma

### Tests
- **`tests/test_real_time_feed.py`** — 38 tests (modelos, cache, normalizador, FoggEngine, ConflictDetector, PostValidator, SuggestionGenerator)
- **`tests/test_core.py`** — actualizado: novita en registry, tests OpenAI-compatibles
- **`tests/test_protocol_contracts.py`** — tests de anthropic/gemini reemplazados por OpenAI-compatibles; eliminado test de `gemini_url`
- **`tests/test_threat_feed_ui.py`** — 6 tests de integración UI (añadidos en Fase 2)
- **`tests/test_cola_eventos.py`** — 12 tests de colas de eventos (añadidos en Fase 2)
- **107 tests pasan** en la suite no-Tkinter (sin red)

### Resultados de tests
```
tests/test_real_time_feed.py     ... 38 passed
tests/test_threat_feed.py        ... 18 passed (legacy intacto)
tests/test_threat_feed_ui.py     ...  6 passed (integración UI)
tests/test_core.py               ... 38 passed
tests/test_protocol_contracts.py ...  7 passed
tests/test_queue_semantics.py    ... 26 passed
tests/test_cola_eventos.py       ... 12 passed
tests/test_context_approval.py   ...  8 passed
                                  ─────
Total no-UI                      ... 153 passed
```

---

## Lo que sigue (Fase 2 — restante)

### ✅ 1. Integrar en UI (`tukul_ui/app.py`) — COMPLETADO
- Botón "Generar sugerencia de impacto…" en el diálogo `manage_references`
- Pipeline completo en hilo separado:
  1. `FeedOrchestrator.fetch_all()` → obtiene datos de fuentes
  2. `FoggEngine.analyze()` → análisis Fogg
  3. `ConflictDetector.detect()` → contradicciones entre fuentes
  4. `SuggestionGenerator.generate(llm_callable)` → LLM genera sugerencia
  5. `PostValidator.validate()` → validación post-generación
- Resultado mostrado en la conversación como `ContextArticle` con `source_id = "suggestion:<uuid>"`
- Autorización automática vía `ContextApprovalCache`
- Confirmación previa con `askyesno` informando de conexiones salientes
- Manejo de errores: LLM no configurado, fetch fallido, LLM no genera, validación con issues

### 3. Adaptadores futuros (cuando se necesiten)
- NIST NVD (si se quiere fuente alternativa)
- ENISA
- OWASP
- NCSC
- Semantic Scholar
- MITRE CAPEC

---

## Arquitectura clave a recordar

### Pipeline de generación de sugerencias
```
FeedOrchestrator.fetch_all()
  → FeedNormalizer.normalize(entries)
    → FoggEngine.analyze(entries)
      → ConflictDetector.detect(entries)
        → SuggestionGenerator.generate(fogg, conflicts, entries)
          → PostValidator.validate(suggestion)
```

### Proveedores LLM activos
| Proveedor | Endpoint | Protocolo |
|---|---|---|
| `deepinfra` | `https://api.deepinfra.com/v1/openai/chat/completions` | OpenAI Chat Completions |
| `novita` | `https://api.novita.ai/v3/openai/chat/completions` | OpenAI Chat Completions |
| `openai_compatible` | URL configurable por el usuario | OpenAI Chat Completions |

### Política de red
- `urllib` puro con `NO_REDIRECT_OPENER` de `http_safety.py`
- Timeout fijo, backoff exponencial con jitter, techo de bytes
- Sin dependencias HTTP externas (ni `requests`, ni `aiohttp`)

### Seguridad
- Fetch solo bajo demanda explícita del usuario (botón + confirmación)
- No hay scheduler ni polling automático
- Sugerencias pasan por `ContextApprovalCache` antes de llegar al prompt

---

## Archivos editados/creados

### Fase 1 (real_time_feed + impact_analyzer)

| Archivo | Acción |
|---|---|
| `tukul_core/models.py` | Editado — añadidas 5 dataclasses nuevas al final |
| `tukul_core/impact_analyzer.py` | Creado — pipeline Fogg completo |
| `tukul_core/real_time_feed/` (directorio) | Creado — paquete completo |
| `tukul_core/real_time_feed/__init__.py` | Creado |
| `tukul_core/real_time_feed/cache.py` | Creado |
| `tukul_core/real_time_feed/normalizer.py` | Creado |
| `tukul_core/real_time_feed/orchestrator.py` | Creado |
| `tukul_core/real_time_feed/adapters/__init__.py` | Creado |
| `tukul_core/real_time_feed/adapters/base.py` | Creado |
| `tukul_core/real_time_feed/adapters/nvd.py` | Creado |
| `tukul_core/real_time_feed/adapters/epss.py` | Creado |
| `tukul_core/real_time_feed/adapters/kev.py` | Creado |
| `tukul_core/real_time_feed/adapters/mitre_attack.py` | Creado |
| `tukul_core/real_time_feed/adapters/arxiv.py` | Creado |
| `tests/test_real_time_feed.py` | Creado — 38 tests |
| `docs/decisions/ADR-0003-real-time-query-and-impact-suggestions.md` | Creado |

### Fase 1b (proveedores LLM)

| Archivo | Acción |
|---|---|
| `tukul_core/llm.py` | Editado — eliminados 5 providers, agregado `novita` |
| `tukul_core/example.toml` | Editado — perfil `novita` agregado, `deepseek` eliminado |
| `tests/test_core.py` | Editado — tests actualizados a OpenAI-compatible |
| `tests/test_protocol_contracts.py` | Editado — tests anthropic/gemini reemplazados; eliminado `test_gemini_url` |
| `docs/CONFIGURATION.md` | Editado — providers y paths actualizados |

### Renombre Articulador → Tukul

| Archivo | Acción |
|---|---|
| `tukul_core/` (antes `articulador_core/`) | Renombrado (git mv) |
| `tukul_ui/` (antes `articulador_ui/`) | Renombrado (git mv) |
| `tukul.py` (antes `articulador.py`) | Renombrado (git mv) |
| `tukul_core/__init__.py` | Editado — docstring |
| `tukul_core/logging_config.py` | Editado — logger name, paths |
| `tukul_core/storage.py` | Editado — config path, keyring |
| `tukul_core/autosave.py` | Editado — autosave path |
| `tukul_core/llm.py` | Editado — system prompt |
| `tukul_core/threat_feed.py` | Editado — User-Agent |
| `tukul_core/real_time_feed/adapters/*.py` | Editado — User-Agent (5 archivos) |
| `tukul_ui/app.py` | Editado — class name, display strings, file extension (~30 ocurrencias) |
| `tukul_ui/ui_state.py` | Editado — docstring |
| `tukul_ui/context_approval.py` | Editado — docstring |
| `tukul_ui/llm_session_manager.py` | Editado — comentario |
| `tukul_ui/__init__.py` | Editado — docstring |
| `tests/*.py` | Editado — imports, class references, strings (17 archivos) |
| `pyproject.toml` | Editado — name, entry point, packages, isort, ruff |
| `scripts/quality-gate.sh` | Editado — paths mypy/pytest/coverage |
| `.github/workflows/ci.yml` | Editado — paths, binary names |
| `.github/workflows/build-release.yml` | Editado — asset names, pyinstaller, dist paths |
| `.gitignore` | Editado — `articulador.png` → `tonal.png` |
| `docs/*.md`, `README.md`, `CHANGELOG.md` | Editado — ~20 documentos |
| `.claude/settings.json` | Editado — package paths |

---

### Fase 2 — Refactor de adaptadores (sesión 2026-09-28)

| Archivo | Acción |
|---|---|
| `tukul_core/threat_feed.py` | Editado — wrapper completo sobre los 5 adaptadores; añadidos `fetch_mitre_attack()`, `fetch_arxiv()`, parámetros `include_mitre`/`include_arxiv` en `build_threat_context()` |
| `tukul_core/real_time_feed/adapters/arxiv.py` | Editado — añadidos `import random`, `TimeoutError`/`OSError`, jitter real en `_sleep()` |
| `tukul_core/real_time_feed/adapters/mitre_attack.py` | Editado — añadidos `import random`, `TimeoutError`/`OSError`, jitter real en `_sleep()` |
| `tukul_core/real_time_feed/adapters/nvd.py` | Editado — jitter real en `_sleep()` (consistente con EPSS/KEV) |
| `tukul_core/real_time_feed/adapters/epss.py` | Editado — jitter real en `_sleep()` |
| `tukul_core/real_time_feed/adapters/kev.py` | Editado — jitter real en `_sleep()` |
| `tests/test_threat_feed.py` | Editado — eliminado `ResponseTooLargeError` de imports (no usado); migrado test de backoff a `EpssAdapter._sleep()` |
| `docs/archive/IMPLEMENTATION_SUMMARY.md` | Editado — añadida nota de actualización (2026-09-28) |
| `docs/SESSION_CONTINUITY.md` | Editado — esta misma actualización |

### Fase 2 — Integración UI de sugerencias de impacto (sesión 2026-09-29)

| Archivo | Acción |
|---|---|
| `tukul_ui/app.py` | Editado — añadidos imports de `impact_analyzer`, `FeedOrchestrator`, `ConsumerSuggestion`; constante `FEED_CACHE_DIR`; botón "Generar sugerencia de impacto…" en `manage_references`; métodos `_fetch_impact_suggestion()`, `_on_impact_suggestion_ready()`, `_on_impact_suggestion_error()` |
| `docs/SESSION_CONTINUITY.md` | Editado — actualizado "Lo que sigue" |

---

## Notas técnicas

- **Python**: 3.11+
- **Gestor de paquetes**: `uv`
- **Tests**: `pytest` con `pytest-mock`
- **UI**: Tkinter (`tkinter` estándar)
- **LLM**: API compatible con OpenAI vía `tukul_core/llm.py` (DeepInfra + Novita AI)
- **No hay dependencias HTTP externas**: todo es `urllib` puro
- **Migración de datos**: `~/.config/articulador/` y `~/.local/state/articulador/` existentes en disco no se migran automáticamente; el usuario debe copiar manualmente o crear symlinks

### Fase 2 — CorrelationEngine e IdeaGenerator (sesión 2026-09-29)

| Archivo | Acción |
|---|---|
| `tukul_core/models.py` | Añadidos — `CorrelationGroup` y `ArticleIdea` (`@dataclass(frozen=True)`) |
| `tukul_core/impact_analyzer.py` | Añadidos — `CorrelationEngine` (correlación determinista por CVE, tópicos y keywords) y `IdeaGenerator` (5 reglas + LLM opcional para enriquecer) |
| `tukul_ui/app.py` | Reemplazado pipeline anterior (`SuggestionGenerator`) por `CorrelationEngine` + `IdeaGenerator`; nuevo diálogo `_show_idea_selection_dialog()` para seleccionar una idea entre múltiples generadas; añadido `_reaplicar_tema_ideas()` |
| `docs/SESSION_CONTINUITY.md` | Editado — esta actualización |

### Fase 2 — Limpieza de imports obsoletos (sesión 2026-09-29)

| Archivo | Acción |
|---|---|
| `tukul_ui/app.py` | Eliminados imports de `FoggEngine`, `ConflictDetector`, `PostValidator`, `SuggestionGenerator`, `ConsumerSuggestion` (ya no se usan en la UI; las clases permanecen en `impact_analyzer.py` para compatibilidad) |
| `docs/SESSION_CONTINUITY.md` | Editado — esta actualización |
