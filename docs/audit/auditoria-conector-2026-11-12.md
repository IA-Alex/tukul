# Auditoría conector-fullstack — Tukul (2026-11-12)

Verifica, con evidencia, que cada llamada saliente del cliente Tukul (UI +
`tukul_core`) tiene contraparte real en los proveedores externos, y que el
resultado declarado se produce. Método: lectura estática + ejecución real de
solo lectura contra los endpoints públicos (en directorio temporal).

## 1. Alcance y contexto

- **Transportes:** HTTP/HTTPS con `urllib` puro (`NO_REDIRECT_OPENER`): LLM
  (OpenAI-compatible / Anthropic / Gemini), búsqueda GDELT y feeds oficiales
  (NVD, EPSS, CISA KEV, MITRE ATT&CK, arXiv).
- **Flujos:** F-01 ideas de artículo (`IdeasController` → `FeedOrchestrator`);
  F-02 contexto CVE (`build_threat_context`); F-03 búsqueda web; F-04 LLM.
- **Revisado en:** `da73a1b` (worktree sucio: `Articulos/`, `.superdesign/`).

## 2. Dictamen

**FALLA-CONFIRMADA.** El flujo F-02 y F-03 funcionan; F-01 (único consumidor de
`FeedOrchestrator`) no podía completarse. MITRE nunca respondía y el
enriquecimiento NVD∩EPSS nunca cruzaba. Severidad: crítico 1 · alto 1 · medio 2
· bajo 3.

## 3. Matriz de trazabilidad (resumen)

| ID | Origen | Proveedor | Estado |
|---|---|---|---|
| T-01 | `llm.py` `_request` OpenAI | DeepInfra/Novita/compatible | OK |
| T-02/03 | `llm.py` protocolos Anthropic/Gemini | Anthropic/Gemini | HUÉRFANA (UI) → H-05 |
| T-06 | `GdeltProvider.search` | GDELT DOC 2.0 | OK |
| T-07 | `NvdAdapter.fetch` | NVD API v2 | OK |
| T-08 | `KevAdapter.normalize` | CISA KEV | DESAJUSTE → H-01 |
| T-09 | `EpssAdapter.fetch` sin `cve_ids` | FIRST EPSS | DESAJUSTE → H-03 |
| T-10 | `MitreAttackAdapter.fetch` | MITRE CTI | DESAJUSTE → H-02 |
| T-11 | `ArxivAdapter.fetch` | arXiv API | OK |
| T-12 | `FeedNormalizer.normalize_all` | interno | DESAJUSTE → H-01 |

## 4. Hallazgos

### H-01 — [CRÍTICO] El pipeline de ideas siempre falla por fechas naive
- **Evidencia (E2E):** `fetch_all(24h)` →
  `TypeError: can't compare offset-naive and offset-aware datetimes` en
  `normalizer.py:43`. Causa: `kev.py:86` (`dateAdded` sin hora) y `nvd.py:161`
  (`published` de NVD sin `Z`: `'2026-11-11T22:17:10.820'`).
- **Impacto:** ninguna idea de artículo se genera.
- **Corrección:** fijar UTC en ambos adaptadores + saneo al releer el caché.

### H-02 — [ALTO] MITRE ATT&CK excede el techo de bytes y nunca aporta
- **Evidencia:** `Content-Length: 49257997` (49.3 MB) vs `MAX_RESPONSE_BYTES`
  32 MB; ejecución real: «supera el límite de bytes».
- **Corrección:** techo a 64 MB y cache solo con `attack-pattern`.

### H-03 — [MEDIO] El enriquecimiento NVD∩EPSS nunca cruza
- **Evidencia:** `NVD∩EPSS = 0`; EPSS sin `cve_ids` devuelve 100 filas del día.
- **Corrección:** re-consultar EPSS acotado a los CVE de NVD, en lotes de 100.

### H-04 — [MEDIO] `EpssAdapter.fetch` viola el contrato de `SourceAdapter`
- **Corrección:** ampliar el ABC con `**kwargs` y alinear los cinco adaptadores.

### H-05 — [BAJO] El README promete proveedores no seleccionables
- **Corrección:** describir los tres proveedores reales y el uso de «Compatible
  con OpenAI» para el resto.

### H-06 — [BAJO] arXiv expone URLs `http://` como `url` de `FeedEntry`
- **Evidencia:** `arxiv.py:147` `url=paper_id`, con `paper_id` = `atom:id`
  (`http://arxiv.org/abs/…`).
- **Corrección:** `_arxiv_url_https` publica el enlace en HTTPS; `source_id`
  intacto. Verificado: 100/100 entradas reales en https.

### H-07 — [BAJO] El perfil de ejemplo declaraba un proveedor genérico
- **Evidencia:** `tukul.example.toml` usaba `provider = "openai_compatible"` en
  los perfiles `deepinfra`/`novita`, perdiendo identidad, hint y validación de
  endpoint.
- **Corrección:** cada perfil declara su id real; test de regresión que verifica
  que todo perfil del ejemplo usa un `provider` de `PROVIDERS` y una ruta de
  chat completa.

### H-08 — [MEDIO] El cache de MITRE no se compartía entre consultas
- **Evidencia (runtime, debugger + ejecución):** tras `fetch()`,
  `adaptador._cache` tiene datos pero `MitreAttackAdapter._cache` es `None`:
  `self._cache = [...]` creaba un atributo de instancia. Como el orquestador hace
  `adapter_cls()` por consulta, el cache de 1 h nunca se aprovechaba y cada
  consulta re-descargaba ~49 MB. Medido en vivo: 5,57 s por descarga; con el
  cache, la 2.ª instancia responde en 0,3 ms.
- **Corrección:** escribir en la clase (`cls = type(self); cls._cache = …`).
  Regresión con dos instancias (patrón real del orquestador).

## 5. Operaciones sin correspondencia
- Protocolos Anthropic/Gemini: implementados pero sin proveedor seleccionable en
  la UI (ver H-05).
- `FeedOrchestrator.available_sources()`: expuesto pero sin consumidor de UI.
- `include_mitre`/`include_arxiv` de `build_threat_context`: solo alcanzables por
  parámetro, no desde el diálogo.

## 6. No verificado
- Cuotas/límites reales de los proveedores en uso sostenido.
- Comportamiento de proxies corporativos sobre el opener sin redirects.
- Flujo UI completo del diálogo de ideas contra red real (se validó el pipeline
  por ejecución directa, no por clic en la Tk).

## 7. Plan de corrección

| Orden | Hallazgo | Cambio mínimo | Verificación |
|---|---|---|---|
| 1 | H-01 | UTC en NVD/KEV + caché | `fetch_all` real sin `TypeError`; tests de fechas |
| 2 | H-03 | EPSS dirigido por CVE, en lotes | `NVD∩EPSS > 0`; test de troceo |
| 3 | H-04 | `**kwargs` en el ABC | mypy limpio; test de contrato |
| 4 | H-02 | techo 64 MB + cache de técnicas | MITRE produce técnicas; test de cache |
| 5 | H-05 | README fiel | — |
| 6 | H-06 | URL https del `atom:id` | 100/100 entradas arXiv en https |
| 7 | H-07 | ids reales en el ejemplo | test sobre `tukul.example.toml` |
| 8 | H-08 | cache de clase en MITRE | 2 consultas → 1 descarga (5,57 s → 0,3 ms) |

## Estado

Corregidos y verificados H-01 a H-08. Cobertura 87.75 %, 709 pruebas, ruff y
mypy limpios, quality gate local verde.
