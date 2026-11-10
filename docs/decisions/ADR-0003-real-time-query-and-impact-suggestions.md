# ADR-0003: consulta en tiempo real a fuentes oficiales y generación de sugerencias de impacto

STATUS: Accepted

## CONTEXT

Tukul necesita agregar la capacidad de consultar fuentes oficiales de
ciberseguridad e IA (NVD, MITRE, CISA, arXiv, NIST, ENISA, OWASP, NCSC) en
tiempo real, bajo demanda explícita del usuario, y generar sugerencias de
impacto para artículos de concientización usando principios de psicología del
consumo (Fogg Behavior Model) sin caer en amarillismo, psicofancia ni
validaciones vacías.

Ya existe `threat_feed.py` que consulta NVD + EPSS + CISA KEV para contexto
CVE. La nueva funcionalidad extiende ese patrón a más fuentes y añade un
pipeline de análisis cualitativo que no existía.

## DECISION

### 1. Nuevo módulo `tukul_core/real_time_feed/`

Paquete con submodulos:

- **`adapters/`**: Cada fuente oficial implementa `SourceAdapter` (ABC).
  - `base.py`: clase base abstracta con `fetch()` y `normalize()`.
  - `nvd.py`, `epss.py`, `kev.py`: refactor de `threat_feed.py` existente.
  - `mitre_attack.py`: MITRE ATT&CK vía STIX/TAXII.
  - `arxiv.py`: arXiv API para papers cs.CR y cs.AI.
  - (futuros: NIST, ENISA, OWASP, NCSC, Semantic Scholar, MITRE CAPEC)
- **`orchestrator.py`**: `FeedOrchestrator` coordina fetch paralelo con
  timeouts, degradación granular y callback de progreso.
- **`cache.py`**: `FeedCache` con TTL (archivo JSON, misma política de
  escritura atómica que `storage.py`).
- **`normalizer.py`**: unifica formatos dispares a `FeedEntry`, deduplica
  por ID, filtra por relevancia y etiqueta por tema/tipo.

### 2. Nuevo módulo `tukul_core/impact_analyzer.py`

> **Nota de vigencia (2026-11-10):** el pipeline Fogg aquí descrito
> (`FoggEngine` → `ConflictDetector` → `SuggestionGenerator` → `PostValidator`)
> **se retiró** en 0.4.0. La UI nunca lo consumió: terminó usando solo
> `CorrelationEngine` + `IdeaGenerator` (sección 4 de esta ADR). La decisión
> original se conserva como registro histórico; la arquitectura vigente está en
> `docs/ARCHITECTURE.md`. Los tipos `FoggAnalysis`, `SourceConflict` y
> `ConsumerSuggestion` permanecen en `models.py`.

- **`FoggEngine`**: aplica Fogg Behavior Model (Motivación + Habilidad +
  Desencadenante) sobre `FeedEntry[]`.
- **`ConflictDetector`**: detecta contradicciones entre fuentes oficiales.
- **`SuggestionGenerator`**: construye prompt estructurado para el LLM
  existente y parsea la respuesta a `ConsumerSuggestion`.
- **`PostValidator`**: verifica que la sugerencia generada no contenga
  afirmaciones sin respaldo, psicofancia, validaciones vacías ni
  incoherencias.

### 3. Nuevos tipos en `models.py`

- `FeedSource`: fuente oficial consultable.
- `FeedEntry`: entrada normalizada de cualquier fuente.
- `FoggAnalysis`: análisis Fogg (motivación, habilidad, desencadenantes).
- `SourceConflict`: contradicción detectada entre fuentes.
- `ConsumerSuggestion`: sugerencia de impacto completa con fundamentación.

### 4. `threat_feed.py` como wrapper de compatibilidad

La API pública existente (`build_threat_context`, `fetch_nvd_recent`,
`fetch_epss`, `fetch_kev`, `ThreatFeedError`) se mantiene idéntica. Debajo
usa los adaptadores del nuevo paquete. No se rompe ningún llamador ni test.

### 5. Política de red

Misma que `threat_feed.py` y `llm.py`: urllib puro,
`NO_REDIRECT_OPENER` de `http_safety.py`, timeout fijo, tope de reintentos
con backoff exponencial y jitter, techo de bytes en la respuesta. Sin
dependencias HTTP nuevas.

### 6. Política de autorización

Las sugerencias entran como `ContextArticle` con `source_id`
`"suggestion:<uuid>"`, pasan por `ContextApprovalCache` antes de llegar al
prompt. El usuario aprueba explícitamente.

### 7. Política de seguridad

El fetch nunca es automático. Solo se dispara desde acción explícita del
usuario (botón "Generar sugerencia de impacto") con confirmación previa
(`messagebox.askyesno`). No hay scheduler ni polling.

## ALTERNATIVES

- **Usar solo el LLM para generar sugerencias sin pipeline estructurado**:
  rechazado porque el LLM solo puede alucinar fuentes, caer en psicofancia
  o generar validaciones vacías. El pipeline de fuentes reales + validación
  post-generación es necesario para cumplir "no psicofancia, no validación
  vacía, sin incoherencias".
- **Integrar cada fuente directamente en `threat_feed.py`**: rechazado
  porque el archivo crecería sin cohesión. El patrón de adaptadores separa
  responsabilidades y permite probar cada fuente de forma aislada.
- **Usar `requests` o `aiohttp`**: rechazado para mantener cero
  dependencias externas de red. urllib con el opener personalizado es
  suficiente y ya está probado.

## CONSEQUENCES

- Los adaptadores son intercambiables y testeables por separado.
- El `threat_feed.py` existente no se rompe (wrapper de compatibilidad).
- La validación post-generación añade latencia pero es necesaria para
  cumplir el requisito de no psicofancia.
- El caché con TTL reduce fetches repetidos dentro de la misma sesión.
- Las fuentes oficiales pueden cambiar su API; cada adaptador encapsula
  ese riesgo.

## SECURITY_IMPACT

- Misma superficie que `threat_feed`: el opener sin redirects protege
  contra exfiltración. Si una fuente futura requiere API key, se usa el
  mismo sistema env/keyring/sesión que los perfiles LLM.
- El fetch bajo demanda con confirmación explícita mantiene el control
  documentado en `SECURITY.md`.
- La validación post-generación reduce el riesgo de que el LLM genere
  contenido engañoso o dañino.

## TESTING_IMPACT

- Tests unitarios para cada adaptador con mocks HTTP (mismo patrón que
  `tests/test_threat_feed.py`).
- Tests del `FeedCache` (TTL, persistencia, desalojo).
- Tests del `FoggEngine` con casos borde (datos insuficientes,
  contradicciones).
- Tests del `PostValidator` (detecta psicofancia, validaciones vacías,
  afirmaciones sin fuente).
- Tests de regresión para `threat_feed.py` (la API pública no cambia).
- Tests de integración del flujo completo con mocks.
