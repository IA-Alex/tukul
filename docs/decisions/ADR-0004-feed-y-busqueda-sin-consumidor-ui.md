# ADR-0004: API de feed/búsqueda sin consumidor de UI — exponer o documentar

STATUS: Accepted

## CONTEXT

La auditoría conector-fullstack del 2026-11-13
(`docs/audit/auditoria-conector-2026-11-13.md`, H-03) confirmó tres superficies
públicas expuestas por `tukul_core` que **ningún consumidor de la UI alcanza**,
ni siquiera la propia app:

1. `FeedOrchestrator.available_sources()`
   (`tukul_core/real_time_feed/orchestrator.py:197`): devuelve los IDs y
   etiquetas de las fuentes registradas. Solo se define; `grep` sobre
   `tukul_ui`, `tukul_core` y `scripts` no encuentra llamadas.
2. `build_threat_context(include_mitre=..., include_arxiv=...)`
   (`tukul_core/threat_feed.py:422`): los dos flags solo son alcanzables por
   parámetro. `contexto_dialogo.py:184` llama `build_threat_context(hours=...)`
   a secas, así que el diálogo de contexto CVE nunca añade MITRE ATT&CK ni
   arXiv.
3. Protocolo `anthropic_messages`
   (`tukul_core/llm.py`): implementado y cubierto por pruebas de
   contrato, pero `PROVIDERS` (`llm.py:81`) solo registra los tres
   OpenAI-compatibles (OpenAI-compatible, DeepInfra, Novita), así que la UI no
   puede seleccionarlos.

Ninguna de las tres rompe un flujo: son capacidades presentes pero no usables,
y su existencia sin decisión documentada es deuda de mantenimiento (código que
hay que conservar y probar sin beneficio para el usuario).

## DECISION

Se decide **mantenerlas como API programática de `tukul_core` y documentarlo.
Ninguna se cablea a la UI en este ciclo**; cada una queda con dueño y motivo
explícitos:

1. **`available_sources()`** — se conserva como API de `tukul_core` para
   consumidores programáticos (scripts, tests, futuras pantallas de
   configuración de fuentes). Documentado en `docs/ARCHITECTURE.md`. No se
   cablea a la UI.
2. **`include_mitre` / `include_arxiv`** — se conservan como parámetros de
   `build_threat_context`. Exponerlos como casillas en el diálogo de contexto
   CVE queda como **mejora de producto en seguimiento**: el diálogo usa hoy una
   única confirmación (`askyesno`) y añadir controles requiere rediseño del
   cuadro y sus pruebas, fuera del alcance de la auditoría. Mientras no se
   cableen, el paquete CVE sigue conteniendo solo NVD + EPSS + KEV, que es el
   comportamiento actual y probado.
3. **Protocolo Anthropic** — se mantiene implementado y probado como
   soporte de transporte para perfiles personalizados. La UI sigue sin
   ofrecerlos como selector hasta que exista una decisión de producto explícita
   (evita prometer proveedores que el usuario no puede elegir, ver H-05 de la
   auditoría del 2026-11-12).

## CONSEQUENCES

- El código huérfano deja de ser silencioso: cada superficie tiene dueño y
  motivo documentados.
- (1) y (3) no consumen UI ni producto; su coste es mantener las pruebas de
  contrato que ya existen.
- (2) queda como mejora acotada y verificable cuando se aborde: al activar el
  flag, el paquete debe incluir el bloque MITRE/arXiv y un test debe fijar que
  el parámetro llega a `build_threat_context`.
- Si en el futuro se decide cablear (1), (2) o (3), la decisión debe revisarse
  aquí.
