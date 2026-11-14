# Auditoría conector-fullstack — Tukul (2026-11-13)

Segunda pasada. Verifica, con evidencia, que cada llamada saliente del cliente
Tukul (`tukul_ui` + `tukul_core`) tiene contraparte real en los proveedores
externos y que el resultado declarado se produce. Además comprueba si los
hallazgos de la corrida anterior (`docs/audit/auditoria-conector-2026-11-12.md`,
H-01..H-08) siguen corregidos y busca desalineaciones nuevas.

Método: lectura estática simbólica (`archivo:línea` en ambos lados) + ejecución
de la suite de contrato/integración local + sondeo de solo lectura contra las
API públicas. Nada se ejecutó contra entornos compartidos de escritura.

## 1. Alcance y contexto

- **Objetivo:** confirmar correspondencia conector↔proveedor y detectar
  desalineaciones residuales o nuevas.
- **Transportes:** HTTP/HTTPS con `urllib` puro vía `NO_REDIRECT_OPENER`
  (`tukul_core/http_safety.py:33`). No hay gRPC, colas ni WebSocket.
- **Superficies cliente↔proveedor incluidas:**
  - LLM: `tukul_core/llm.py::LLMClient` (protocolos `openai_compatible`,
    `anthropic_messages`, `gemini_generate_content`) → DeepInfra / Novita /
    OpenAI-compatible / Anthropic / Gemini.
  - Feeds oficiales: `tukul_core/real_time_feed/adapters/*` registrados en
    `adapters/__init__.py:18` → NVD, FIRST EPSS, CISA KEV, MITRE ATT&CK, arXiv,
    OpenAlex, HuggingFace Papers.
  - Wrapper legado: `tukul_core/threat_feed.py::build_threat_context`.
  - Búsqueda: `tukul_core/search/providers.py::GdeltProvider` → GDELT DOC 2.0.
- **Flujos:** F-01 ideas (`IdeasController`→`FeedOrchestrator`); F-02 contexto
  CVE (`build_threat_context`); F-03 búsqueda web (`SearchOrchestrator`); F-04
  LLM (`LLMSessionManager`, `probar conexión`).
- **Excluido:** keyring, almacenamiento local, UI pura (sin red), y los
  proveedores Anthropic/Gemini como flujo de producto (no son seleccionables en
  la UI; ver §5).
- **Evidencia disponible:** suite de contrato local
  (`tests/test_llm_http_contract.py`, `tests/test_protocol_contracts.py`,
  `tests/test_real_time_feed.py`, `tests/test_mitre_attack_adapter.py`,
  `tests/test_openalex_adapter.py`, `tests/test_huggingface_papers_adapter.py`,
  `tests/test_search.py`, `tests/test_stix_stream.py`, `tests/test_threat_feed.py`).
- **Revisado en:** `95b5c50` (`test: asienta el worker de autoindexado antes de
  las pruebas de cierre`), rama `master`, **worktree limpio**.

## 2. Dictamen

- **Estado: FUNCIONAL-PARCIAL.**
- **Resumen:** el núcleo (F-01, F-02, F-04) está verificado con evidencia de
  contrato e integración local, y los 8 hallazgos previos siguen corregidos en
  `95b5c50`. F-03 (búsqueda GDELT) falla de forma reproducible contra la API
  real: el proveedor responde `429 Too Many Requests` y el cliente **no tiene
  reintento ni respeto de intervalo**, a diferencia de todos los adaptadores de
  feed. Además, `SearchQuery.language` es un campo muerto del contrato. No hay
  hallazgo crítico que rompa F-01/F-02/F-04.
- **Severidad:** crítico 0 · alto 0 · medio 2 · bajo 1.
- **Cobertura:** identificados 19 · trazados 19 · contratos 14 · E2E 4 · fallos 2
  · pendientes 3.

## 3. Matriz de trazabilidad

| ID | Origen | Transporte/operación | Proveedor | Resultado | Evidencia | Estado |
|---|---|---|---|---|---|---|
| T-01 | `llm.py:311` `_request` (default) | POST chat/completions | DeepInfra/Novita/OpenAI-compat | 200 parseado | `test_llm_http_contract.py:293`, `test_protocol_contracts.py:59` | OK |
| T-02 | `llm.py:302` rama `anthropic_messages` | POST messages | Anthropic | cabeceras correctas | `test_llm_http_contract.py:299` | OK (sin consumidor UI) |
| T-03 | `llm.py:307` rama `gemini_generate_content` | POST generateContent | Gemini | cabeceras correctas | `test_llm_http_contract.py:312` | OK (sin consumidor UI) |
| T-04 | `llm.py:299-316` errores HTTP | `error.message` | cualquier proveedor | mensaje propagado y acotado | `test_llm_http_contract.py:344` | OK |
| T-05 | `llm.py:258` `_open_with_retry` | reintento transitorio | cualquier proveedor | backoff + Retry-After | `test_llm_http_contract.py:193` | OK |
| T-06 | `search/providers.py:49` `GdeltProvider.search` | GET DOC 2.0 artlist | GDELT | **429 sin reintento** | E2E: `RuntimeError: GDELT respondió 429.` (ver H-01) | **DESAJUSTE → H-01** |
| T-07 | `adapters/nvd.py:46` `NvdAdapter.fetch` | GET cves/2.0 | NVD API v2 | `vulnerabilities[]` | `test_real_time_feed.py` (red), `_dates.py:6` | OK |
| T-08 | `adapters/epss.py:44` `EpssAdapter.fetch` | GET data/v1/epss | FIRST EPSS | `data[]`; `?cve=` filtra | `test_real_time_feed.py:859` | OK |
| T-09 | `adapters/kev.py:45` `KevAdapter.fetch` | GET known_exploited_*.json | CISA KEV | `vulnerabilities[]` | `test_threat_feed.py` | OK |
| T-10 | `adapters/mitre_attack.py:76` | GET enterprise-attack.json | MITRE CTI | STIX `objects[]` | `test_mitre_attack_adapter.py` (38), `test_stix_stream.py` | OK |
| T-11 | `adapters/arxiv.py:73` `_fetch_category` | GET api/query | arXiv Atom | `entry[]` | `test_real_time_feed.py:310-600` | OK |
| T-12 | `adapters/openalex.py:49` `OpenAlexAdapter.fetch` | GET works `concepts.id` | OpenAlex | `results[]` (19.1M hits) | sondeo live 200 + `meta.count`; `test_openalex_adapter.py` | OK |
| T-13 | `adapters/huggingface_papers.py:52` | GET api/daily_papers | HuggingFace | `list[]` | `test_huggingface_papers_adapter.py` | OK |
| T-14 | `orchestrator.py:83` EPSS dirigido por CVE | re-consulta por CVE | FIRST EPSS | lotes de 100 | `test_real_time_feed.py:748,784` | OK |
| T-15 | `search/models.py:19` `SearchQuery.language` | — | GDELT | **nunca se envía** | `providers.py:50-57` no lo usa | **DESAJUSTE → H-02** |
| T-16 | `search/models.py:48` `SearchResult` | — | interno | exige `https://` | `test_search.py:23` | OK |
| T-17 | `http_safety.py:33` opener | — | todos | 3xx → error | `test_llm_http_contract.py:227` | OK |
| T-18 | `real_time_feed/_dates.py:25` | — | NVD/KEV/arXiv/MITRE | fecha con zona UTC | `test_fechas_feed_regresion.py` | OK |
| T-19 | `threat_feed.py:422` `build_threat_context` | wrapper adaptadores | NVD/EPSS/KEV/MITRE/arXiv | degradación granular | `test_threat_feed.py` (18) | OK |

## 4. Hallazgos

### H-01 — [MEDIO] `GdeltProvider.search` no reintenta ni respeta el rate-limit de GDELT
- **Flujos:** F-03.
- **Evidencia:** [E2E] ejecución contra la API real con el código del repo
  (`tukul_core.search.GdeltProvider.search`): `RuntimeError: GDELT respondió
  429.` en dos intentos separados 6 s; un tercer intento directo con el mismo
  `USER_AGENT` y `NO_REDIRECT_OPENER` también devolvió `HTTP Error 429`. El
  proveedor advierte por texto: *«Please limit requests to one every 5 seconds»*.
  Estático: `tukul_core/search/providers.py:62-71` captura `HTTPError` y lanza
  `RuntimeError` **sin** bucle de reintento, backoff ni `Retry-After`; no hay
  constante de intervalo en el módulo (contraste con `arxiv.py:40`
  `ARXIV_MIN_REQUEST_INTERVAL = 3.0` y con `nvd.py:60-79`, que sí reintentan).
- **Síntoma:** la búsqueda web bajo demanda devuelve error de proveedor y cero
  resultados ante cualquier ráfaga o cuota compartida agotada.
- **Causa:** [CONFIRMADO] ausencia de lógica de resiliencia en el proveedor de
  búsqueda; es el único conector saliente sin reintentos.
- **Impacto:** F-03 no puede completarse en condiciones normales de cuota
  compartida (el free tier de GDELT es por IP y esta auditoría lo agotó). No
  afecta a F-01/F-02/F-04.
- **Corrección mínima propuesta:** añadir en `GdeltProvider.search` un bucle
  acotado (`MAX_ATTEMPTS = 3`) que reintente `429/5xx` con backoff exponencial y
  jitter respetando `Retry-After`, más un `GDELT_MIN_REQUEST_INTERVAL` de ≥ 5 s
  entre llamadas del mismo proceso (mismo patrón que `nvd.py::_sleep` y
  `arxiv.py::_wait_for_rate_limit`). Alternativa compatible: reusar un helper de
  resiliencia compartido que ya existe por duplicado en los adaptadores.
- **Regresión recomendada:** test de contrato con `ThreadingHTTPServer` local que
  devuelva 429 una vez y 200 después, verificando que `search()` reintenta y
  devuelve resultados (equivalente a `test_llm_http_contract.py:193`).

### H-02 — [MEDIO] `SearchQuery.language` es un campo muerto del contrato
- **Flujos:** F-03.
- **Evidencia:** [ESTÁTICO] declarado y validado en
  `tukul_core/search/models.py:19`, pero `GdeltProvider.search`
  (`tukul_core/search/providers.py:50-57`) construye los parámetros `query`,
  `mode`, `format`, `maxrecords`, `timespan`, `sort` y **no** incluye
  `language`. `SearchResult.language` (models.py:44) solo se **lee** de la
  respuesta (`providers.py:94`). La UI nunca lo fija:
  `tukul_ui/contexto_dialogo.py:359` crea `SearchQuery(query.strip(),
  max_results=20)`.
- **Síntoma:** ninguno visible; el campo aparenta filtrar por idioma pero no
  tiene efecto.
- **Causa:** [CONFIRMADO] parámetro añadido al modelo sin cablearlo al
  proveedor.
- **Impacto:** deuda de contrato: un consumidor futuro que fije
  `language="es"` creerá estar filtrando sin filtrar. GDELT sí soporta
  `sourcelang:` en la query, así que la intención es implementable.
- **Corrección mínima propuesta:** o bien enviar
  `sourcelang:` en `query` cuando `query.language` no sea `None`
  (`providers.py:50`), o bien eliminar el campo del modelo. Decidir en
  `docs/decisions`.
- **Regresión recomendada:** test que afirme que, con `language="es"`, el
  parámetro `query` enviado contiene `sourcelang:spanish`.

### H-03 — [BAJO] `FeedOrchestrator.available_sources()` sigue sin consumidor y `include_mitre`/`include_arxiv` siguen inalcanzables desde la UI
- **Flujos:** F-01, F-02.
- **Evidencia:** [ESTÁTICO] `available_sources` solo se define
  (`orchestrator.py:197`); `grep` sobre `tukul_ui`, `tukul_core`, `scripts` no
  encuentra llamadas. `include_mitre`/`include_arxiv` solo existen como
  parámetros de `build_threat_context` (`threat_feed.py:422-427`); `grep` en
  `tukul_ui` no los fija, y `contexto_dialogo.py:184` llama
  `build_threat_context(hours=...)` a secas.
- **Síntoma:** ninguno funcional.
- **Causa:** [CONFIRMADO] API expuesta sin cablear (ya reportado en la corrida
  previa §5; no se corrigió ni se decidió).
- **Impacto:** bajo: capacidades presentes pero no usables por el usuario; ruido
  de mantenimiento.
- **Corrección mínima propuesta:** decidir explícitamente —cablearlas a la UI o
  documentarlas como API programática en `docs/decisions`— para que dejen de ser
  huérfanas silenciosas.
- **Regresión recomendada:** n/a (decisión de producto).

## 5. Operaciones sin correspondencia

- **Protocolos Anthropic/Gemini** (`llm.py:301-310`): implementados y con
  contrato verificado por pruebas, pero **ningún proveedor seleccionable en la
  UI** los usa (`PROVIDERS`, `llm.py:81`, solo registra OpenAI-compat/DeepInfra/
  Novita). Uso externo/por decisión de producto; no es un fallo.
- **`FeedOrchestrator.available_sources()`**: huérfana (ver H-03).
- **`include_mitre`/`include_arxiv`**: alcanzables solo por parámetro (ver H-03).
- No se hallaron rutas de proveedor expuestas sin cubrir por ningún conector de
  este repo más allá de las anteriores.

## 6. No verificado y límites

- **Forma de respuesta 200 de GDELT:** no pudo confirmarse hoy porque la cuota
  compartida por IP estaba agotada (`429` persistente). El parser
  (`providers.py:77-100`) declara leer `articles[].url/title/snippet/seendate/
  domain/language/sourcecountry/sourcecollection`; su corrección contra un 200
  real queda **pendiente**. Para cerrarlo: reintentar desde una IP sin cuota
  consumida, o completar H-01 (el reintento permitirá observar el 200).
- **Estabilidad del filtro `concepts.id` de OpenAlex:** el sondeo devolvió 200
  con `count = 19.159.628`, así que **existe y responde**, pero OpenAlex ha
  marcado `concepts` como legacy frente a `topics`; no verifiqué si el conjunto
  devuelto sigue siendo «inteligencia artificial» con precisión. No lo clasifico
  como desajuste por falta de evidencia decisiva.
- **Cuotas/límites reales en uso sostenido** (NVD sin key, EPSS, OpenAlex free
  tier) y **comportamiento de proxies corporativos** sobre el opener sin
  redirects: fuera del repo, no verificado.
- **Anthropic/Gemini** verificados solo con doble de contrato local, no contra el
  proveedor real (no son flujo de producto).

## 7. Plan de corrección

| Orden | Hallazgo | Dependencia | Cambio mínimo | Verificación de cierre | Estado |
|---|---|---|---|---|---|
| 1 | H-01 | — | Reintento + intervalo ≥5 s en `GdeltProvider.search` (`providers.py`) | Test de contrato local 429→200; búsqueda real devuelve resultados | **REPARADO** |
| 2 | H-02 | — | Enviar `sourcelang:` o eliminar `SearchQuery.language` | Test de query con `language` fijado | **REPARADO** |
| 3 | H-03 | Decisión de producto | Cablear a UI o documentar como API programática | ADR en `docs/decisions` | Pendiente |
| 4 | §6 | H-01 | Observar un 200 real de GDELT y validar el parser | Búsqueda `days`/`max_results` con resultados y fechas correctas | Bloqueado por cuota IP |

### Reparación aplicada (2026-11-13)

Editado con edición simbólica de Serena sobre `tukul_core/search/providers.py`:

- **H-01:** nuevas constantes `GDELT_MIN_REQUEST_INTERVAL = 5.0`,
  `RETRYABLE_STATUS`, `MAX_ATTEMPTS = 3`, `BACKOFF_BASE_SECONDS`,
  `BACKOFF_MAX_SECONDS`; `GdeltProvider.__init__` con `_last_request_at`;
  `search()` pasa por `_open_with_retry`; nuevos helpers `_wait_for_rate_limit`
  (respeta el intervalo entre llamadas) y `_sleep` (backoff con jitter +
  `Retry-After`). Un 429 transitorio ya no falla de inmediato.
- **H-02:** `_build_query` inyecta `sourcelang:<language>` en la query cuando
  `SearchQuery.language` está fijado.

Verificación:
- `tests/test_search.py`: 5 pruebas nuevas (sourcelang inyectado y ausente;
  429→200 reintentado; 429 persistente agota `MAX_ATTEMPTS` y lanza; 404
  no reintentable falla al primer intento). 9/9 en verde.
- Suite de conectores (12 ficheros): **196 passed**.
- `ruff check .` y `mypy tukul_core tukul_ui` limpios (62 ficheros).
- E2E real: la llamada ahora tarda ~38 s e intenta 3 veces antes de fallar,
  frente al fallo instantáneo anterior. El 429 persiste porque la IP de esta
  máquina tiene la cuota compartida de GDELT agotada (respuesta sin
  `Retry-After`, texto «Please limit requests to one every 5 seconds»),
  condición externa que ningún código de cliente puede resolver.

### Hallazgo fuera de alcance (pre-existente, no introducido por esta reparación)

`tests/test_app_ramas.py::TestPipelineDeIdeas::test_desarrollar_la_idea_la_deja_como_contexto_autorizado`
falla por `pytest-timeout` **también en el árbol limpio** (`95b5c50`, verificado
con `git stash`). Causa: el test parchea `self.app._llm_de_ideas`, pero la ruta
real (`tukul_ui/ideas.py:185`) usa `self._llm_de_ideas` dentro de
`IdeasController`, que resuelve al cliente real (`LLMClient().complete` contra
`https://api.example.com/v1/chat/completions`), un host inexistente que cuelga
hasta el timeout. No tiene relación con la búsqueda GDELT ni con esta auditoría.
