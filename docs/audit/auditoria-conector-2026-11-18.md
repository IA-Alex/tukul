# Auditoría conector-fullstack — Tukul (2026-11-18)

Tercera pasada sobre la superficie de **adaptadores de fuentes externas**
(`tukul_core/real_time_feed/adapters/*` + `tukul_core/threat_feed.py`). Verifica,
con evidencia, que cada operación del conector (adaptador) tiene contraparte real
en el proveedor y que el resultado declarado se produce. Método: lectura estática
simbólica (`archivo:línea` en ambos lados) + suite de contrato local + sondeo de
solo lectura contra las API públicas. Nada se ejecutó contra entornos compartidos
de escritura.

Esta pasada es de alcance acotado a los adaptadores; el transporte LLM,
la búsqueda GDELT y el enrutado de la UI no se re-auditan aquí (cubiertos en
[`auditoria-conector-2026-11-13.md`](auditoria-conector-2026-11-13.md) y
[`auditoria-conector-proveedor-2026-11-13.md`](auditoria-conector-proveedor-2026-11-13.md)).

## 1. Alcance y contexto

- **Objetivo:** confirmar correspondencia adaptador↔proveedor externo y detectar
  desalineaciones residuales o nuevas, tras los `H-01..H-08` del informe
  `auditoria-conector-2026-11-12` y los `H-01..H-03` del
  `auditoria-conector-2026-11-13` (esa serie numeró con prefijo `H-`; este
  informe usa `DF-`, según `CONTRIBUTING.md`).
- **Stack/topología/transportes:** HTTP/HTTPS con `urllib` puro vía
  `NO_REDIRECT_OPENER` (`tukul_core/http_safety.py:36`). No hay gRPC, colas,
  WebSocket ni IPC. Proveedores: NVD API v2, FIRST EPSS, CISA KEV, MITRE ATT&CK
  (GitHub CTI), arXiv API, OpenAlex, HuggingFace Papers.
- **Flujos incluidos:**
  - **F-01** ideas de artículo (`IdeasController._ejecutar_pipeline` →
    `FeedOrchestrator.fetch_all`).
  - **F-02** contexto CVE (`build_threat_context` → NVD+EPSS+KEV, con MITRE/arXiv
    opcionales).
- **Flujos excluidos:** LLM (F-04), búsqueda web (F-03) y UI pura (sin red).
- **Evidencia disponible:** `tests/test_real_time_feed.py`,
  `tests/test_mitre_attack_adapter.py`, `tests/test_openalex_adapter.py`,
  `tests/test_huggingface_papers_adapter.py`, `tests/test_stix_stream.py`,
  `tests/test_threat_feed.py`, `tests/test_fechas_feed_regresion.py`; sondeo live
  de solo lectura de los 7 endpoints.
- **Revisado en:** `461130f` (rama `master`, **worktree sucio**: `.gitignore`,
  `evals/proveedor_tukul.py`, `tests/test_evals_asercciones.py` modificados y
  cuatro `evals/_tmp_mimo_*.yaml` sin rastrear; ninguno toca la superficie
  auditada).

## 2. Dictamen

- **Estado: FUNCIONAL-PARCIAL** (los cuatro hallazgos accionables de esta pasada
  quedan reparados; DF-004 es decisión documentada).
- **Resumen:** los siete adaptadores tienen contraparte real y su contrato de
  forma coincide con lo que devuelve el proveedor hoy (verificado con sondeo
  live 200). El cruce NVD∩EPSS sigue correcto: confirmé contra la API real que la
  forma en coma `?cve=A,B` —la que usa el código— devuelve una fila por CVE,
  mientras que la repetida `?cve=A&cve=B` devuelve una sola (la última). Las
  correcciones de las pasadas anteriores siguen vigentes. En esta pasada se
  repararon DF-001 (atribución de timeout en el orquestador), DF-002 (docstring),
  DF-003 (código muerto) y DF-005 (parser STIX anclado a la raíz); DF-004 se
  documentó como intencional en ADR-0003.
- **Severidad:** crítico 0 · alto 0 · medio 1 · bajo 4.
- **Cobertura:** identificados 22 · trazados 22 · contratos 16 · E2E 8 · fallos 5
  · pendientes 0.

## 3. Matriz de trazabilidad

| ID | Origen | Transporte/operación | Proveedor | Resultado | Evidencia | Estado |
|---|---|---|---|---|---|---|
| T-01 | `adapters/nvd.py:46` `NvdAdapter.fetch` | GET `rest/json/cves/2.0` | NVD API v2 | 200; `vulnerabilities[]`, `published` sin zona | live 200 `totalResults=1322`; `nvd.py:83-128`; `test_real_time_feed.py` | OK |
| T-02 | `adapters/epss.py:44` `EpssAdapter.fetch` (`cve_ids`) | GET `data/v1/epss?cve=A,B` | FIRST EPSS | 200; una fila por CVE | live 200: `cve=A,B` → 2 filas; `cve=A&cve=B` → 1 fila; `test_real_time_feed.py:860,880` | OK |
| T-03 | `adapters/epss.py:56` EPSS sin `cve_ids` | GET `?date=YYYY-MM-DD` | FIRST EPSS | 200; `data[]` del día | `epss.py:56`; en F-01 el orquestador lo re-consulta por CVE (`orchestrator.py:108`) | OK |
| T-04 | `adapters/kev.py:45` `KevAdapter.fetch` | GET `known_exploited_vulnerabilities.json` | CISA KEV | 200; `vulnerabilities[]` | live 200; `kev.py:80-104`; `test_threat_feed.py` | OK |
| T-05 | `adapters/mitre_attack.py:59` `fetch` | GET `mitre/cti/master/…enterprise-attack.json` | MITRE CTI (GitHub) | 200; STIX `objects[]` (~49 MB) | live 200, 5.4 s; `_stix_stream.py`; `test_stix_stream.py` | OK |
| T-06 | `adapters/mitre_attack.py:123` `_techniques_in_window` | filtro local `modified ≥ since` | — | 0 técnicas en 24 h | live `fetch(24)` → 0; `mitre_attack.py:127-133` | OK (sin datos) → DF-004 |
| T-07 | `adapters/arxiv.py:73` `_fetch_category` | GET `export.arxiv.org/api/query` | arXiv Atom | 200; `entry[]` en `http://` | live 200 cs.CR/cs.AI (~125 KB c/u); `arxiv.py:113-140` | OK |
| T-08 | `adapters/arxiv.py:193` `_wait_for_rate_limit` | pausa ≥3 s entre peticiones | arXiv ToU | respetado | `arxiv.py:193-207`; `test_real_time_feed.py:526,564` | OK |
| T-09 | `adapters/openalex.py:49` `fetch` | GET `works?filter=concepts.id:…` | OpenAlex | 200; `results[]` | live 200; `openalex.py:98-129`; `test_openalex_adapter.py` | OK |
| T-10 | `adapters/huggingface_papers.py:52` `fetch` | GET `api/daily_papers` | HuggingFace | 200; `list[].paper` | live 200 (50 items); `huggingface_papers.py:95-126` | OK |
| T-11 | `orchestrator.py:108` `_recover_epss_for_nvd` | re-consulta EPSS por CVE de NVD | FIRST EPSS | lotes de 100 | `orchestrator.py:118-150`; `test_real_time_feed.py:749,785` | OK |
| T-12 | `orchestrator.py:152-190` `_fetch_parallel` | hilos + `join(timeout=45)` | todos | fuente lenta >45 s **se descarta sin error** | `orchestrator.py:178-190` | **DESAJUSTE → DF-001** |
| T-13 | `http_safety.py:36` `NO_REDIRECT_OPENER` | 3xx → `HTTPError` | todos | sin seguir redirecciones | `http_safety.py:26-36`; `arxiv.py:24-28` documenta el 301 | OK |
| T-14 | `real_time_feed/_dates.py:25` `parse_feed_date` | normalización de fecha | NVD/KEV/arXiv/MITRE/OpenAlex/HF | datetime con zona UTC | `_dates.py:25-48`; `test_fechas_feed_regresion.py` | OK |
| T-15 | `normalizer.py:64` `enrich_nvd_with_epss_and_kev` | cruce local NVD∩EPSS∩KEV | — | tags EPSS/KEV aplicados | `normalizer.py:75-116`; `test_real_time_feed.py:277` | OK |
| T-16 | `threat_feed.py:422` `build_threat_context` | wrapper sobre adaptadores | NVD/EPSS/KEV (+MITRE/arXiv) | `(packet, files)`, degradación granular | `threat_feed.py:276-478`; `test_threat_feed.py` | OK |
| T-17 | `threat_feed.py:139` `fetch_nvd_recent` | wrapper `NvdAdapter` | NVD | `ThreatFeedEntry[]` | `threat_feed.py:139-169` | OK |
| T-18 | `cache.py:27` `FeedCache` | JSON local + TTL | — | escritura atómica 0600 | `cache.py:85-105`; `test_real_time_feed.py:161-242` | OK |
| T-19 | `mitre_attack.py:172` `_read_bounded` | lectura acotada de bytes | — | **no se usa en `fetch()`** | `fetch` usa `iter_stix_objects` (`mitre_attack.py:84`) | **DESAJUSTE → DF-003** |
| T-20 | `_dates.py:3` / `nvd.py:166` docstring | «las cinco fuentes del feed» | — | el `REGISTRY` tiene **7** | `adapters/__init__.py:18-26` | **DESAJUSTE → DF-002** |
| T-21 | `_stix_stream.py:98` `_encontrar_inicio_lista` | escaneo estructural de la cabecera | MITRE | localiza `"objects"` de la raíz (fuera de cadenas, prof. 1) | `_stix_stream.py:98-176`; `test_stix_stream.py::TestBundleValido` | OK (DF-005 reparado) |
| T-22 | `arxiv.py:210` `_arxiv_url_https` | `atom:id` http → https | arXiv | URL publicada en https | live: `http://arxiv.org/abs/2611.23208v1` → https; `test_real_time_feed.py:479` | OK |

## 4. Hallazgos

### DF-001 — [MEDIO] El orquestador descarta en silencio toda fuente que excede el `join(timeout=45)`

- **Flujos:** F-01.
- **Evidencia:** [ESTÁTICO] `orchestrator.py:178-190`: los hilos se lanzan y luego
  `for t in threads: t.join(timeout=45)`. Si un hilo sigue vivo al vencer los 45 s,
  ni `results[sid]` (línea 170) ni `errors[sid]` (línea 175) llegan a escribirse:
  esa fuente **desaparece del resultado sin entrada en `errors`**. El guardia
  `if not results and errors` (línea 187) solo lanza error si *todas* fallan
  registrando motivo; una fuente que expiró por timeout no aporta motivo al
  mensaje.
- **Síntoma:** una consulta que en realidad falló por lentitud se reporta como si
  la fuente «no hubiera devuelto nada», y el detalle de error agregado (cuando el
  resto también falla) omite la causa del timeout.
- **Causa:** [CONFIRMADO] el `join(timeout=...)` no distingue «terminó» de «seguía
  vivo»; no hay `t.is_alive()` tras el join ni registro de timeout.
- **Impacto:** degradación de la calidad del diagnóstico en F-01. Los proveedores
  con timeout de 30 s y hasta 3 intentos (NVD, EPSS, KEV, MITRE) **pueden** superar
  los 45 s con red lenta o con `Retry-After`; arXiv acumula ≥3 s entre sus dos
  categorías más reintentos. No rompe F-01 si otra fuente responde, pero sesga el
  resultado y oculta la causa. Plausible, no reproducido hoy contra una fuente real
  (ver §6).
- **Corrección mínima propuesta:** tras el join, recorrer `threads` con
  `if t.is_alive(): errors[sid] = "timeout de 45 s"` (requiere asociar cada hilo a
  su `sid`, p. ej. un `dict[str, Thread]`), de modo que la fuente quede registrada
  como error en vez de ausente. Alternativa: `join()` sin timeout y confiar en el
  `HTTP_TIMEOUT` interno de cada adaptador.
- **Regresión recomendada:** test con un adaptador doble que duerme >45 s
  (monkeypatch del timeout a un valor pequeño) y verificar que `errors` contiene el
  `sid` y que el mensaje agregado lo menciona.

### DF-002 — [BAJO] La documentación dice «las cinco fuentes del feed», pero hay siete

- **Flujos:** F-01, F-02.
- **Evidencia:** [ESTÁTICO] `real_time_feed/_dates.py:3` («Las cinco fuentes
  oficiales publican fechas ISO 8601…») y `adapters/nvd.py:166` («…única fuente de
  verdad para las cinco fuentes del feed»). El `REGISTRY` real registra **siete**:
  `adapters/__init__.py:18-26` (nvd, epss, kev, mitre-attack, arxiv,
  huggingface-papers, openalex). OpenAlex y HuggingFace Papers se añadieron después
  sin actualizar el texto, que se declara «única fuente de verdad».
- **Síntoma:** ninguno funcional; la docstring miente sobre su propia cobertura.
- **Causa:** [CONFIRMADO] conteo hardcodeado en prosa que no se actualizó al
  ampliar el registro.
- **Impacto:** bajo: un mantenedor que confíe en «cinco fuentes» puede creer que
  `parse_feed_date` no cubre un adaptador nuevo.
- **Corrección mínima propuesta:** sustituir «cinco» por «las fuentes» (sin número)
  en `_dates.py:3` y `nvd.py:166`, o referir «las fuentes registradas en
  `adapters/__init__.py`».
- **Regresión recomendada:** n/a (documentación). Si se quiere fijar, un test que
  afirme que todo adaptador del `REGISTRY` importa `parse_feed_date` (o su módulo
  `_dates`) mantendría el texto honesto por construcción.

### DF-003 — [BAJO] `MitreAttackAdapter._read_bounded` es código muerto en la ruta de producción

- **Flujos:** F-01, F-02.
- **Evidencia:** [ESTÁTICO] `mitre_attack.py:172-185` define `_read_bounded`, pero
  `fetch()` (`mitre_attack.py:81-94`) lee el cuerpo con `iter_stix_objects`, que
  aplica su propio techo de bytes (`_stix_stream.py:65-68`). El único llamador de
  `_read_bounded` son las pruebas `tests/test_mitre_attack_adapter.py:287-312`
  (`TestReadBounded`), que verifican una función que el producto no invoca.
- **Síntoma:** el techo de bytes de MITRE en producción lo impone `_stix_stream`,
  no el método que las pruebas creen que lo impone.
- **Causa:** [CONFIRMADO] refactor a extracción incremental (`iter_stix_objects`)
  que dejó el método anterior sin retirar.
- **Impacto:** bajo: superficie de test que no cubre el camino real; un cambio en
  `MAX_RESPONSE_BYTES` parece probado por `TestReadBounded` cuando el que actúa es
  el techo de `_stix_stream` (misma constante, distinto código).
- **Corrección mínima propuesta:** eliminar `_read_bounded` de
  `mitre_attack.py` y retirar `TestReadBounded` (el techo ya está probado en
  `tests/test_stix_stream.py:91-93`), o dejar `_read_bounded` con un comentario que
  declare que solo existe por compatibilidad de pruebas.
- **Regresión recomendada:** `tests/test_stix_stream.py::TestTechoDeBytes` ya cubre
  el camino real; no requiere prueba nueva.

### DF-004 — [BAJO] El filtro de ventana de MITRE ATT&CK no puede aportar técnicas con datos reales

- **Flujos:** F-01, F-02.
- **Evidencia:** [E2E] `MitreAttackAdapter().fetch(24)` contra el bundle real
  devolvió **0 técnicas** en 5,4 s (el bundle responde 200; ver T-05). Con una
  ventana amplia (10 años) el mismo adaptador devolvió **867 técnicas**,
  confirmando que el parser y la fuente funcionan y que la causa es solo el
  filtro `modified >= now-24h` (`mitre_attack.py:127-133`).
- **Síntoma:** las correlaciones «MITRE + CVE» de `impact_analyzer.py:334-350` casi
  nunca disponen de técnicas que las sustenten en el flujo real.
- **Causa:** [CONFIRMADO] el filtro por `modified` describe «qué cambió en la
  ventana», no «qué técnicas son relevantes a los CVE de la ventana», y las
  técnicas ATT&CK se modifican con poca frecuencia.
- **Impacto:** bajo: MITRE responde y no falla, pero rara vez aporta. No rompe F-01
  (hay NVD/KEV/arXiv/OpenAlex/HF). **Decisión de producto (2026-11-18): se
  mantiene el filtro como intencional** y se documenta en `ADR-0003` (nota de
  vigencia). Cambiar el criterio a relevancia-por-CVE queda como mejora futura,
  fuera de esta reparación.
- **Corrección aplicada:** nota de vigencia en `ADR-0003` (sección 1). Sin cambio
  de comportamiento.
- **Regresión recomendada:** n/a (decisión documentada).

### DF-005 — [BAJO→MEDIO] El localizador de `"objects"` podía leer la lista equivocada

- **Flujos:** F-01, F-02 (vía MITRE ATT&CK).
- **Evidencia:** [ESTÁTICO + COMPONENTE] `_stix_stream._encontrar_inicio_lista`
  buscaba la **primera** aparición literal de `b'"objects"'` en todo el cuerpo
  (antes: `buffer.find(MARKER)`). Reproducido con un bundle JSON válido donde un
  objeto declara antes una clave anidada `"objects"`:
  `{"meta":{"objects":[{"id":"nested"}]},"objects":[{"id":"real"}]}` →
  `iter_stix_objects` devolvía `[{"id":"nested"}]` y **perdía** `[{"id":"real"}]`
  (evidencia directa del caso J en la corrida del 2026-11-18).
- **Síntoma:** si el bundle de MITRE llegara con una clave `"objects"` antes que la
  raíz, el feed leería objetos ajenos y descartaría las técnicas sin avisar.
- **Causa:** [CONFIRMADO] búsqueda de bytes sin distinguir profundidad de llave ni
  contenido de cadena; el bundle real hoy declara la raíz primero, lo que oculta el
  defecto.
- **Impacto:** bajo hoy (MITRE real no lo dispara), pero **medio** como fragilidad:
  el parser dependía del orden de las claves de una fuente externa y fallaba en
  silencio. La corrección lo hace robusto.
- **Corrección aplicada:** `_encontrar_inicio_lista` ahora escanea la cabecera
  reconociendo la clave `"objects"` **fuera de cadenas** y **a profundidad 1**
  (helpers `_clave_objects_en_raiz` y `_corchete_tras_llave`), sin depender del
  orden de claves.
- **Regresión:** `tests/test_stix_stream.py::TestBundleValido` con cuatro casos
  nuevos (clave anidada previa, cabecera troceada, valor `"objects"`, espacios
  antes del `[`). Los dos del caso raíz **fallan antes** (`['nested'] != ['real']`)
  y pasan después.



## 5. Operaciones sin correspondencia

- `FeedOrchestrator.available_sources()` (`orchestrator.py:197`) sigue sin
  consumidor; ya decidido como API programática en
  [`ADR-0004`](../decisions/ADR-0004-feed-y-busqueda-sin-consumidor-ui.md). No es
  hallazgo nuevo.
- `build_threat_context(include_mitre=…, include_arxiv=…)` (`threat_feed.py:422`):
  alcanzable solo por parámetro, decisión vigente en ADR-0004.
- `MitreAttackAdapter._read_bounded` (`mitre_attack.py:172`): huérfana de
  producción (ver DF-003).
- **Todos los adaptadores del `REGISTRY` (7) tienen consumidor** vía
  `FeedOrchestrator.fetch_all` (F-01) o `build_threat_context` (F-02). No hay rutas
  de proveedor expuestas sin cubrir por ningún conector de este repo más allá de
  las anteriores.

## 6. No verificado y límites

- **Reproducción de DF-001 con una fuente real:** no logré forzar hoy que un
  proveedor supere los 45 s (NVD, EPSS, KEV, arXiv y MITRE respondieron dentro del
  presupuesto; MITRE tardó 5,4 s). La causa del hallazgo es estática y cierta; el
  síntoma concreto queda **pendiente de reproducir**. Para cerrarlo: inyectar
  latencia (proxy local o `ThreadingHTTPServer` que duerma) en un entorno
  local/efímero y observar que la fuente no aparece ni en `results` ni en `errors`.
- **Marcador literal de `_stix_stream`:** confirmado y **corregido** en esta
  misma corrida (ver DF-005). Queda cerrado.
- **Cuotas/límites reales en uso sostenido:** NVD sin key, EPSS, OpenAlex free
  tier (el mensaje de OpenAlex advierte de un presupuesto diario compartido por IP),
  HuggingFace y arXiv. No medí el agotamiento sostenido; solo un 200 puntual por
  endpoint.
- **Comportamiento de proxies corporativos** sobre el opener sin redirects y el
  efecto de un proxy que devuelva 3xx: fuera del repo, no verificado.
- **Estabilidad del filtro `concepts.id` de OpenAlex:** respondió 200 con
  `results[]`, pero OpenAlex marca `concepts` como legacy frente a `topics`. No
  corregí el filtro por falta de evidencia de que haya dejado de ser «IA».

## 7. Plan de corrección

| Orden | Hallazgo | Dependencia | Cambio mínimo | Verificación de cierre | Estado |
|---|---|---|---|---|---|
| 1 | DF-001 | — | Registrar timeout por fuente tras `join(timeout=45)` en `orchestrator.py:178-190` | Test con adaptador que excede el timeout; `errors` lo menciona | **REPARADO** |
| 2 | DF-003 | — | Retirar `_read_bounded` de `mitre_attack.py` y `TestReadBounded` | Suite de MITRE/STIX en verde tras el retiro | **REPARADO** |
| 3 | DF-002 | — | Quitar el conteo «cinco» en `_dates.py:3` y `nvd.py:166` | Revisión de docstring (n/a regresión) | **REPARADO** |
| 4 | DF-005 | — | Anclar `"objects"` a la raíz en `_stix_stream.py` (fuera de cadenas, profundidad 1) | Tests del caso J: fallan antes, pasan después | **REPARADO** |
| 5 | DF-004 | Decisión de producto (ADR-0003) | Documentar el filtro por `modified` como intencional | Nota de vigencia en ADR-0003 | **REPARADO (documentado)** |

### Reparación aplicada (2026-11-18)

Baseline antes de editar: `tests/test_real_time_feed.py`,
`test_mitre_attack_adapter.py`, `test_stix_stream.py`, `test_threat_feed.py`,
`test_openalex_adapter.py`, `test_huggingface_papers_adapter.py`,
`test_fechas_feed_regresion.py` → **160 passed**; `ruff check` y
`mypy tukul_core tukul_ui` limpios.

- **DF-001:** nueva constante `FETCH_THREAD_TIMEOUT_SECONDS = 45`
  (`orchestrator.py:233`); `_fetch_parallel` asocia cada hilo a su `sid` y, tras
  el `join`, registra en `errors` toda fuente que siga viva (`t.is_alive()`),
  en vez de dejarla desaparecer. Regresión:
  `tests/test_real_time_feed.py::TestFeedOrchestrator::test_una_fuente_que_excede_el_timeout_se_registra_como_error`
  (verificada en ambas direcciones).
- **DF-003:** retirado `MitreAttackAdapter._read_bounded` (código muerto; el techo
  de bytes real lo impone `_stix_stream.iter_stix_objects`). Se conserva el test
  del techo por el camino de producción (`fetch()`), renombrado a
  `TestTechoDeBytes`.
- **DF-002:** «las cinco fuentes» → «las fuentes» en `_dates.py:3` y `nvd.py:166`.
- **DF-005:** `_stix_stream._encontrar_inicio_lista` reescrito para localizar la
  clave `"objects"` fuera de cadenas y a profundidad 1 (helpers
  `_clave_objects_en_raiz`, `_corchete_tras_llave`). Cuatro tests nuevos en
  `TestBundleValido`; dos fallan antes (`['nested'] != ['real']`) y pasan después.
- **DF-004:** nota de vigencia en `ADR-0003` (filtro por `modified` intencional).

Verificación: suite completa **908 passed, 0 omitidas** (4:32); `ruff check .` y
`mypy tukul_core tukul_ui` limpios (68 ficheros); bundle real de MITRE parseado
(867 técnicas en ventana amplia, 0 en 24 h). El gate local, además, incluye un
`RUF100` en `evals/proveedor_tukul.py:241` (trabajo no commiteado del usuario,
ajeno a esta auditoría) que se resolvió retirando el `noqa` inerte.
