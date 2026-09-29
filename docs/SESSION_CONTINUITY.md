# Continuidad de Sesión — Articulador

> Última actualización: 28/9/2026
> Rama: `master` — Commit `c816aa7`

## Estado actual

Se completó la **Fase 1: Fundación del módulo real_time_feed y analizador de impacto**.
La Fase 2 (refactor de `threat_feed.py` como wrapper, integración UI) está lista para comenzar.

---

## Lo que se implementó

### Modelos (`articulador_core/models.py`)
- `FeedSource`, `FeedEntry`, `FoggAnalysis`, `SourceConflict`, `ConsumerSuggestion`
- Todas `@dataclass(frozen=True)`

### Paquete `articulador_core/real_time_feed/`
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

### Analizador de impacto (`articulador_core/impact_analyzer.py`)
- `FoggEngine` — evalúa Motivación + Habilidad + Desencadenantes (Fogg Behavior Model)
- `ConflictDetector` — detecta contradicciones NVD vs EPSS vs KEV por CVE ID
- `SuggestionGenerator` — construye prompt estructurado para LLM, parsea respuesta a `ConsumerSuggestion`
- `PostValidator` — verifica sin psicofancia, validaciones vacías, incoherencias, impacto/audiencia válidos

### Documentación
- `docs/decisions/ADR-0003-real-time-query-and-impact-suggestions.md` — ADR aceptado

### Tests (`tests/test_real_time_feed.py`)
- **38 tests** cubriendo: modelos, cache, normalizador, FoggEngine, ConflictDetector, PostValidator, SuggestionGenerator
- Todos pasan en el commit actual

### Resultados de tests
```
tests/test_real_time_feed.py ... 38 passed
tests/test_threat_feed.py    ... 18 passed (legacy intacto)
tests/test_cola_eventos.py   ... 14 passed
tests/test_flujo_revision.py ... varios fallan por Tkinter (pre-existente, no relacionado)
tests/test_interfaz.py       ... varios fallan por Tkinter (pre-existente, no relacionado)
tests/test_tema.py           ... falla por Tkinter (pre-existente, no relacionado)
```

---

## Lo que sigue (Fase 2)

### 1. Refactorizar `threat_feed.py` como wrapper
- Reemplazar implementaciones internas por llamadas a los adaptadores del nuevo paquete
- Mantener API pública idéntica: `build_threat_context`, `fetch_nvd_recent`, `fetch_epss`, `fetch_kev`, `ThreatFeedError`
- No romper ningún test existente

### 2. Integrar en UI (`articulador_ui/app.py`)
- Botón "Generar sugerencia de impacto" que invoque:
  1. `FeedOrchestrator.fetch_all()` → obtiene datos de fuentes
  2. `FoggEngine.analyze()` → análisis Fogg
  3. `SuggestionGenerator.generate()` → LLM genera sugerencia
  4. `PostValidator.validate()` → validación post-generación
- Mostrar resultados en la conversación como `ContextArticle` con `source_id = "suggestion:<uuid>"`
- Pasar por `ContextApprovalCache` (confirmación del usuario)

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

### Política de red
- `urllib` puro con `NO_REDIRECT_OPENER` de `http_safety.py`
- Timeout fijo, backoff exponencial con jitter, techo de bytes
- Sin dependencias HTTP externas (ni `requests`, ni `aiohttp`)

### Seguridad
- Fetch solo bajo demanda explícita del usuario (botón + confirmación)
- No hay scheduler ni polling automático
- Sugerencias pasan por `ContextApprovalCache` antes de llegar al prompt

---

## Archivos editados/creados en Fase 1

| Archivo | Acción |
|---|---|
| `articulador_core/models.py` | Editado — añadidas 5 dataclasses nuevas al final |
| `articulador_core/impact_analyzer.py` | Creado — pipeline Fogg completo |
| `articulador_core/real_time_feed/` (directorio) | Creado — paquete completo |
| `articulador_core/real_time_feed/__init__.py` | Creado |
| `articulador_core/real_time_feed/cache.py` | Creado |
| `articulador_core/real_time_feed/normalizer.py` | Creado |
| `articulador_core/real_time_feed/orchestrator.py` | Creado |
| `articulador_core/real_time_feed/adapters/__init__.py` | Creado |
| `articulador_core/real_time_feed/adapters/base.py` | Creado |
| `articulador_core/real_time_feed/adapters/nvd.py` | Creado |
| `articulador_core/real_time_feed/adapters/epss.py` | Creado |
| `articulador_core/real_time_feed/adapters/kev.py` | Creado |
| `articulador_core/real_time_feed/adapters/mitre_attack.py` | Creado |
| `articulador_core/real_time_feed/adapters/arxiv.py` | Creado |
| `tests/test_real_time_feed.py` | Creado — 38 tests |
| `docs/decisions/ADR-0003-real-time-query-and-impact-suggestions.md` | Creado |

---

## Notas técnicas

- **Python**: 3.13+
- **Gestor de paquetes**: `uv`
- **Tests**: `pytest` con `pytest-mock`
- **UI**: Tkinter (`tkinter` estándar)
- **LLM**: API compatible con OpenAI vía `articulador_core/llm.py`
- **No hay dependencias HTTP externas**: todo es `urllib` puro
