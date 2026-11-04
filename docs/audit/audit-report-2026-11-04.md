# Auditoría Full-Stack — Tukul

**Fecha:** 2026-11-04
**Commit auditado:** `e1459c9` (`fix: cierra el resto del renombre a Tukul y dos fallos de feed/ideas`) — árbol de trabajo limpio
**Skill:** `audit-fullstack`
**Herramientas:** Serena (navegación simbólica: overviews y búsqueda de referencias), inspección directa de archivos, ejecución real de la puerta de calidad (ruff, mypy, pytest con cobertura bajo `xvfb-run`).
**Ámbito:** todo el repositorio — código de producto (`tukul_core`, `tukul_ui`, `tukul.py`), tests, CI/CD, documentación, empaquetado y configuración.

---

## 1. Resumen ejecutivo

### Veredicto: 🟡 **ENTREGABLE CON RESERVAS — la base es sólida; hay una inconsistencia entre el gate local y CI, deuda documental y escala pendiente en la UI.**

A diferencia de la auditoría anterior (2026-11-02, árbol roto por un refactor a medio hacer), el repositorio está hoy **en verde real**:

| Verificación | Comando ejecutado | Resultado |
|---|---|---|
| Lint | `.venv/bin/python -m ruff check .` | ✅ `All checks passed!` |
| Tipos | `.venv/bin/python -m mypy tukul_core tukul_ui tukul.py` | ✅ `Success: no issues found in 42 source files` |
| Suite + cobertura | `xvfb-run -a .venv/bin/python -m pytest -q --cov=...` | ⚠️ **425 passed, 1 failed**, cobertura **81 %** (umbral 70 %) |
| Tk operativo | `xvfb-run -a python -c 'tkinter.Tk()'` | ✅ `Tk OK` |

El único fallo (`test_internal_imports_resolve_without_conftest`) es un **artefacto del entorno local**: el paquete no está instalado en `.venv` (`pip install -e .` no se ejecutó en este checkout). CI lo instala explícitamente, así que allí pasaría. **Pero** `scripts/quality-gate.sh` no instala el proyecto antes de correr pytest y, por tanto, **falla en un checkout limpio aunque el código esté correcto**: es un defecto del gate, no del producto.

### Contraste con la auditoría del 2026-11-02

Los 25 hallazgos previos (1 CRÍTICO, 5 ALTOS, 10 MEDIOS, 9 BAJOS) están cerrados y verificables: el refactor de `articulador_core` → `tukul_core` está completo, `pyproject.toml` usa `packages.find` (el subpaquete `real_time_feed` ya no puede quedar fuera de la rueda), la cancelación por petición sustituyó al evento compartido, y CI tiene puertas reales (skips = fallo, `pip-audit` con hashes, Bandit `-lll -ii`, instalación aislada).

**Lo que sigue pendiente es de segunda generación**: consistencia gate↔CI, un caso borde de configuración que deja la app en silencio "sin configurar", documentación que se contradice con el código sobre la fuente CVE, y un `app.py` de 3.085 líneas / clase `TukulApp` con ~200 métodos que agrava cada cambio futuro.

### Conteo de hallazgos

| Severidad | Cantidad |
|---|---|
| 🔴 CRÍTICO | 0 |
| 🟠 ALTO | 3 |
| 🟡 MEDIO | 6 |
| 🔵 BAJO | 5 |
| **Total** | **14** |

> **Nota de calibración.** Tukul es una aplicación **de escritorio local (Tkinter + urllib)**: no hay servidor, ni base de datos, ni superficie HTTP entrante. El riesgo de seguridad absoluto es bajo y los ejes "Backend/API", "Datos" y "Despliegue" se reinterpretan como: *cliente HTTP y adaptadores de proveedor*, *persistencia en archivos (TOML/JSON/autosave)* y *empaquetado PyInstaller + releases*. Un hallazgo es "ALTO" cuando degrada de forma significativa la mantenibilidad o debilita una garantía que la documentación declara.

---

## 2. Contexto del repositorio (Paso 1)

| Dimensión | Valor |
|---|---|
| **Propósito** | Editor conversacional local de artículos Markdown con LLM remoto opcional |
| **Tipo** | Aplicación de escritorio (CLI de una orden + ventana Tkinter). **No es web, no hay backend servidor** |
| **Stack** | Python ≥3.11 (CI: 3.11/3.12/3.13), Tkinter, `urllib`, `tomli-w`, `keyring` (extra), `tomllib` |
| **Persistencia** | Archivos locales: `config.toml`, `estado.json`, `autosave/`, proyectos JSON. Sin base de datos |
| **Infra** | GitHub Actions: `ci.yml` (matriz 3 versiones) + `build-release.yml` (PyInstaller Linux/Windows) |
| **Tamaño** | ~7.700 LOC de producto (pico: `tukul_ui/app.py` 3.085; `impact_analyzer.py` 728; `threat_feed.py` 478; `storage.py` 455; `llm.py` 398) + ~7.300 LOC de tests (32 archivos) |
| **Versión** | `0.3.2`; tags `v0.2.1`, `v0.3.0`, `v0.3.2`; CHANGELOG Keep-a-Changelog con sección Unreleased |
| **Docs** | Arquitectura, seguridad, privacidad, operación, testing, releases, 3 ADR, trazabilidad, índice con ownership |
| **Estado** | Producción temprana; suites y lint verdes, deuda estructural acotada |

### Adaptación de ejes

- **Backend/API** → `LLMClient` (`tukul_core/llm.py`) y `LLMSessionManager` como "backend de egress": contrato con 3 protocolos (OpenAI-compatible, Anthropic Messages, Gemini), validación de endpoint, retries y límites de cuerpo.
- **Datos** → `storage.py` (escritura atómica + `fsync` de directorio, permisos preservados, carga defensiva), `estado.json`, autosave.
- **Despliegue** → workflow PyInstaller, lock con hashes, SBOM ausente, checksums no implementados y correctamente declarados como ausentes.

---

## 3. Hallazgos

### 🟠 ALTO

---

#### [ALTO] CI/CD: el gate local no ejecuta las comprobaciones que CI trata como bloqueantes

**Descripción**
- `scripts/quality-gate.sh` se anuncia como "única puerta de calidad local: espejo del pipeline de CI" (README §Calidad, docs/TESTING.md), pero **omite cinco pasos** del workflow: `pip-audit`, `bandit -lll -ii`, verificación de `Tk` en subproceso aislado con `--health`, contrato CLI y la comprobación de `identity`/`--config` del health check.
- Además, el propio gate **no instala el paquete** antes de pytest y **pytest no se invoca con `--strict-markers`/`-W error`**, mientras CI instala con `pip install -e . --no-deps` y `--require-hashes`.

**Evidencia**
- `scripts/quality-gate.sh` (líneas 37-89): solo `ruff`, `mypy`, `verify-install.sh`, `pytest`.
- `.github/workflows/ci.yml` (jobs `test` y `security`): añade `pip_audit --local --skip-editable`, `bandit -r ... -lll -ii`, `Verify health check`, `Verify --config reaches the health check`, `Verify CLI contract`.
- Ejecución real en este entorno: `pytest` → `1 failed ... test_internal_imports_resolve_without_conftest` con `ModuleNotFoundError: No module named 'tukul_core'` (el paquete no está instalado en `.venv`).

**Por qué importa**
- Un desarrollador que confía en el gate local puede fusionar una dependencia con CVE o un hallazgo de seguridad que CI bloqueará 8 minutos después (y lo mismo al contrario: el gate falla por instalación y se acostumbra a ignorarlo).
- "Espejo de CI" es una afirmación de la documentación que el código no cumple: rompe la confianza en los documentos normativos.

**Recomendación**
- Añadir al gate: `python -m pip_audit --local --skip-editable` y `python -m bandit -r tukul_core tukul_ui -lll -ii`, más `python tukul.py --health | grep -q` del perfil esperado.
- Antes de pytest, comprobar instalación y fallar con mensaje accionable: `"$PYTHON" -c "import tukul_core" || echo "Instala con: pip install -e ."`. Mejor aún: que el gate detecte y ofrezca `pip install -e .[dev]`.
- Mover los bloques `Verify *` de `ci.yml` a `scripts/quality-gate.sh` y **llamar al script desde CI** (un solo origen de verdad), o generar el script desde el workflow.

---

#### [ALTO] Arquitectura: `TukulApp` concentra la UI, la máquina de estados de peticiones, la persistencia y el ciclo de vida en un único módulo de 3.085 líneas

**Descripción**
- `tukul_ui/app.py` define la clase `TukulApp(tk.Tk)` con ~200 métodos: construcción de widgets, temas, atajos, menús contextuales, autosave, peticiones LLM, revisión, aprobación de contexto, streaming, cierre, `estado.json`, health/theme, tooltips, diálogos.
- Los workers de red se crean **inline** dentro de tres métodos distintos (`_solicitar_revision`, `_lanzar_envio`, y dos bloques adicionales en líneas 2269 y 2375), cada uno repitiendo el patrón `threading.Thread(target=work, daemon=True)` + `control_queue.put_nowait(...)`.
- La cobertura de `app.py` es la más baja del producto (74 %, 415 líneas sin cubrir) concentrada precisamente en ramas de error y cancelación.

**Evidencia**
- `wc -l tukul_ui/app.py` → `3085`; `grep -n "def work" tukul_ui/app.py` → líneas 1703, 1863, 2269, 2375.
- `docs/ARCHITECTURE.md` declara `TukulApp` como "coordina UI, documento, conversación, requests y cierre": cinco responsabilidades, cuatro de ellas ajenas a Tk.
- La documentación ya admite deuda: `pyproject.toml` desactiva `E701/E702` "porque `tukul_ui/app.py` usa un estilo denso deliberado".

**Por qué importa**
- Cada nueva capacidad (ya ocurrió con el feed CVE y con las ideas) añade un bloque `def work` duplicado; los defectos de cancelación de la auditoría anterior nacieron precisamente de la duplicación del ciclo de petición.
- Es el módulo que bloquea la cobertura: subir del 74 % al 85 % exige ejercitar ramas de error dentro de una clase de 3k líneas.
- El conocimiento de "cómo termina una petición" está disperso entre `_abort_request`, `finish`, `_reset_request_ui`, `_dispatch_ui_event`, `_cancel_active_request` y los workers: cualquier cambio de protocolo toca 6 sitios.

**Recomendación**
- Extraer `RequestLifecycle` (o `RequestController`): un objeto que recibe `profile`, callback de streaming, `control_queue` y `chunk_buffer`, y expone `start()`, `cancel()`, `on_event()`. Los cuatro `def work` se convierten en una sola llamada.
- Extraer `UIStateBookkeeper` (snapshot, saneado, guardado, poda de conversaciones: `_snapshot_estado_ui`, `_guardar_estado_ui`, `_podar_conversaciones`, `_persistir_conversacion_en_memoria`).
- Mantener `TukulApp` como ensamblador: bindings de Tk, construcción de widgets y delegación. Objetivo medible: `app.py` < 1.500 líneas y cobertura del controlador de peticiones ≥ 90 %.
- No exigir reformatear el archivo entero: la extracción ya obliga a módulos nuevos con estilo normal.

---

#### [ALTO] Configuración: un perfil con campos mal tipados se ignora en silencio y el usuario ve "sin configurar" sin causa

**Descripción**
- `_coerce_profile_fields` acepta solo campos con tipo exacto (`int` para `max_output_tokens`, etc.) y **descarta el campo** si no coincide; el perfil se construye con los valores por defecto del dataclass y **se guarda como si fuera válido**. El log registra `Perfil 'x' ignorado por configuración inválida` únicamente si el constructor lanza una excepción, cosa que no ocurre al descartar campos.
- Un `max_output_tokens = 4096.0` (TOML admite flotantes y un editor los produce con facilidad) o `"4096"` como cadena no rompe nada, pero produce un perfil con límites por defecto que no son los del usuario. Si el valor inválido es `enabled` o `model`, el resultado es un perfil deshabilitado o con modelo vacío y el usuario ve "Configura un perfil LLM y una key".

**Evidencia**
- `tukul_core/storage.py:167-184` (`_coerce_profile_fields`): `if isinstance(value, int): kwargs[key] = value` — sin `else: logger.warning(...)`.
- `tukul_core/storage.py:197-240` (`load_profiles`): el `try/except` solo captura la construcción del dataclass.
- `docs/CONFIGURATION.md` promete diagnóstico; `--health` cuenta perfiles habilitados, no campos descartados.

**Por qué importa**
- El modo de fallo es silencioso y engañoso: "la app no responde" y el diagnóstico dice "perfil habilitado" (porque lo está, con los defaults).
- Es exactamente el tipo de defecto que el proyecto ya cerró en la auditoría anterior ("Antes desaparecía en silencio y el usuario veía 'sin configurar'"), pero la rama de coercición quedó fuera.

**Recomendación**
- Registrar un `logger.warning` por campo descartado con nombre de perfil, campo, valor recibido y tipo esperado.
- Exponerlo en `--health` como `N campo(s) ignorado(s) en perfiles: perfiles.x.max_output_tokens (float, se esperaba int)`.
- Alternativa más amable: coerción tolerante explícita (`4096.0` → `4096`; `"4096"` → `4096` con aviso), documentada en `CONFIGURATION.md`.

---

### 🟡 MEDIO

---

#### [MEDIO] Documentación: `SECURITY.md` declara "prototipo no integrado" una capacidad que ya está implementada

**Descripción**
- `docs/SECURITY.md` tiene dos secciones sobre la fuente CVE: una "**implementada**" y otra "**Superficie planeada** … prototipo aislado, no integrado ni invocado por la aplicación". La segunda contradice a la primera y al código.

**Evidencia**
- `docs/SECURITY.md` §"Superficie planeada: fuente de amenazas (CVE)": *"El módulo experimental … no debe considerarse una integración disponible"*.
- `README.md:86-98` y `docs/ARCHITECTURE.md#fuente-de-contexto-de-amenazas-cve`: describen el botón "Añadir CVEs recientes…" como capacidad activa con confirmación.
- `tukul_ui/app.py` invoca `_fetch_threat_feed` desde el diálogo de contexto; existen `tests/test_threat_feed*.py` y `tests/test_threat_feed_ui.py`.

**Por qué importa**
- `docs/README.md` declara `SECURITY.md` como NORMATIVE: un lector de seguridad concluiría que la superficie de red CVE no existe.

**Recomendación**
- Eliminar la sección "planeada" o reescribirla como "histórico: promovida a control actual el 2026-11-02". Añadir a `TRACEABILITY.md` una fila `threat feed CVE`.

---

#### [MEDIO] Testing: la cobertura E2E del flujo LLM depende de dobles; no hay prueba de contrato HTTP real ni de los tres protocolos contra un servidor local

**Descripción**
- Hay tests ricos de unidades (`test_core.py`, `test_real_time_feed.py`, `test_cola_eventos.py`) y de UI con Tk real, pero `tukul_core/llm.py` se ejercita con dobles: no hay un test que levante un `http.server` local y valide SSE real, `Retry-After` real, redirección 302 (no seguida), `Content-Length` excesivo y `http://` no-loopback rechazado de extremo a extremo.
- La matriz de proveedores (`openai_compatible`, `anthropic_messages`, `gemini_generate_content`) solo está cubierta por ramas aisladas; una regresión de payload (p. ej. un cambio de `x-goog-api-key` a `Authorization`) pasaría los tests actuales.

**Evidencia**
- `tukul_core/llm.py` define `_request` con tres ramas; las pruebas no inyectan un servidor que imprima las cabeceras recibidas.
- Cobertura de `llm.py`: 83 % (44 líneas sin cubrir, principalmente retries y errores de red).

**Por qué importa**
- El cliente HTTP es la única frontera crítica del producto: un fallo de contrato rompe la app para todos los usuarios del proveedor afectado y no se detecta hasta producción.

**Recomendación**
- Añadir `tests/test_llm_http_contract.py` con un `ThreadingHTTPServer` en `127.0.0.1:0`: cuatro tests (SSE correcto, `429` con `Retry-After: 1`, `302` que **no** se sigue, body mayor al techo). Marcar como integración (sin red externa) y ejecutar en CI: son milisegundos.

---

#### [MEDIO] Operación: el cierre espera a los hilos con un tope global de 2 s, pero un `open()` HTTP colgado puede dejar el proceso vivo como daemon con la ventana ya destruida

**Descripción**
- `LLMClient._open_with_retry` usa `HTTP_TIMEOUT_SECONDS = 90` y `time.sleep` en el backoff **sin comprobar `cancel_event` durante la espera**. `close()` da a los workers 2 s y luego los deja como daemon. La cancelación durante la conexión inicial solo se detecta al volver del `sleep`/`open`.
- El comportamiento documentado ("no bloquea el proceso") es correcto, pero el usuario no ve ningún diagnóstico: `logger.warning("%d hilo(s) de petición seguían activos al cerrar")` queda en el log, no en la UI ni en `--health`.

**Evidencia**
- `tukul_core/llm.py:170-203`: `time.sleep(self._retry_delay(...))` sin `cancel_event.wait(...)`.
- `tukul_ui/app.py:_esperar_hilos_de_peticion` (timeout 2 s) y `logger.warning`.

**Por qué importa**
- En una red lenta, cerrar Tukul puede dejar un proceso que sigue consumiendo CPU/memoria hasta 90 s. En la práctica el proceso termina porque el hilo es daemon, pero un reportero que envía un stack trace verá el aviso sin explicación de usuario.
- El reintento con `time.sleep` retrasa la cancelación hasta 4 s por intento: el botón "Cancelar" parece no responder.

**Recomendación**
- Cambiar `time.sleep(delay)` por `if cancel_event.wait(delay): return None` en `_open_with_retry`.
- Añadir al `--health` un contador (en `estado.json` o un flag de `logging_config`) `last_shutdown_pending_workers` para diagnóstico.

---

#### [MEDIO] Frontend/UI: `docs/screenshots/tukul.png` es la única referencia visual y no hay pruebas de accesibilidad documentadas (contraste, foco, teclado) más allá de tests de widgets concretos

**Descripción**
- Existen `test_tema.py`, `test_modo_foco.py`, `test_atajos_dialogos.py`, `test_dialogos_modales.py`; son buenos sobre comportamiento, pero no hay un test automatizado que verifique **ratios de contraste AA** del tema (claro/oscuro), ni un recorrido de teclado completo (abrir diálogo → foco inicial → `Tab` → `Esc` → foco devuelto), ni `state_accesible` en todos los estados de `EstadoUI`.

**Evidencia**
- `tukul_ui/estilo.py` (240 líneas) define la paleta; ningún test calcula luminancia relativa.
- `docs/SECURITY.md` no cubre accesibilidad; `README.md` no la menciona.
- `TukulApp.estado_accesible()` existe (línea 1278) pero su cobertura de estados no está fijada por test de tabla.

**Por qué importa**
- Es una app de escritura: el usuario pasa horas en el editor. Un contraste insuficiente o un `Esc` que no devuelve el foco es fricción diaria, y con `tk` los tests pueden detectarlo de forma determinista.

**Recomendación**
- Test unitario `test_contraste_aa` que calcule el ratio WCAG de cada par (texto, fondo) de `estilo.py` y falle si < 4.5 (texto normal) / 3.0 (grande).
- Test tabulado `EstadoUI → estado_accesible()`.
- Test de foco: abrir cada `Toplevel` de `dialogs.py` y afirmar que `focus_get()` está dentro del diálogo y que `Esc` lo cierra devolviéndolo al widget anterior.

---

#### [MEDIO] Entrega: releases sin checksums ni SBOM aunque `docs/RELEASE.md` describe el contrato; la ausencia se declara, pero no hay checklist ejecutable

**Descripción**
- El workflow `build-release.yml` construye dos binarios y publica un Release en tag, pero no genera `sha256sum` ni un SBOM (`syft`/`pip-licenses`). `RELEASE.md` lo admite honestamente ("CHECKSUMS and SIGNING_IF_AVAILABLE no están implementados … no deben anunciarse como garantías"), pero no hay ningún artefacto ni script que lo impida para siempre.
- `uv.lock` está versionado (280 KB) y `requirements-dev.lock` también: dos fuentes de verdad de dependencias que deben actualizarse juntas, sin un test que verifique que coinciden.

**Evidencia**
- `.github/workflows/build-release.yml` (100 líneas): no hay `sha256sum` ni `cyclonedx`.
- `pyproject.toml` + `uv.lock` + `requirements-dev.lock` coexisten.

**Por qué importa**
- Un usuario que descarga `tukul-linux-x86_64` no puede verificar que no fue alterado en tránsito.
- La deriva entre `uv.lock` y `requirements-dev.lock` hará que el gate local (uv) y CI (pip + hashes) usen árboles distintos.

**Recomendación**
- Añadir al job `release`: `sha256sum tukul-* > SHA256SUMS` y subirlo como asset; generar `sbom.cdx.json` con `pip-licenses --format=json` o `syft`.
- Test en CI: comparar los paquetes resueltos de ambos lockfiles (lista de `name==version`) y fallar si divergen.

---

#### [MEDIO] Seguridad: el prompt de contexto se construye por concatenación de texto y el test de "datos no confiables" es heurístico sobre una sola cadena

**Descripción**
- `build_editor_prompt` (usa `prompting.py` de 18 líneas + `impact_analyzer.build_editor_prompt`) serializa a JSON y el `SYSTEM_PROMPT` instruye a no obedecer instrucciones. Es lo correcto para un cliente, pero no hay defensa en profundidad: no se delimita el contenido con marcadores de rol (`<article>…</article>`), no se escapan ni se neutralizan secuencias tipo `</system>` y no hay detección de inyección conocida (patrones `ignore previous instructions`, exfiltración de key).

**Evidencia**
- `tukul_core/llm.py:SYSTEM_PROMPT` (una línea).
- `docs/SECURITY.md` tabla: control = "system prompt trata datos como no confiables"; riesgo residual = "el proveedor/modelo puede ignorar instrucciones".

**Por qué importa**
- Es un riesgo aceptado y bien documentado, pero "solo system prompt" es una única capa. El propio proyecto ya declara que trata todo como dato no confiable: falta la estructura.

**Recomendación**
- En el payload, envolver cada fuente en un objeto con `kind: "data"` y `provenance` (artículo, selección, CVEs, archivo de contexto) y **nunca** interpolar texto fuera de esos campos.
- Test de regresión de visibilidad: un artículo que contiene `</data><system>…` debe aparecer en el payload JSON como contenido escapado, no como estructura.

---

### 🔵 BAJO

---

#### [BAJO] Calidad: `tests/test_auditoria_regresion.py` es un archivo de 1.427 líneas que mezcla dominios

**Evidencia**
- `tests/test_auditoria_regresion.py` (1.427 líneas) concentra tests de seguridad, autosave, límites y cierre, y es el mayor archivo de test del repo.
**Recomendación**
- Repartir por dominio (`test_seguridad_endpoint.py`, `test_autosave.py`, `test_limites.py`) en un cambio sin modificar asserts. Marcador de éxito: ningún archivo de test > 600 líneas.

---

#### [BAJO] Dependencias: `uv.lock` y `requirements-dev.lock` sin verificación de equivalencia

**Evidencia**
- Ambos ficheros en la raíz, mantenidos a mano.
**Recomendación**
- Ver `[MEDIO] Entrega`; si se descarta el paso de CI, retirar `uv.lock` y documentar `uv` como no soportado.

---

#### [BAJO] Docs: `docs/TESTING.md` dice "la suite tarda ~25 s" en `pyproject.toml` pero no hay un presupuesto de rendimiento de la suite ni un aviso si supera un umbral

**Evidencia**
- `pyproject.toml:139` — comentario "la suite entera tarda ~25 s como máximo".
**Recomendación**
- Añadir a CI `--durations=10` y un paso que falle si el total supera 120 s (evita que se degrade en silencio).

---

#### [BAJO] Operación: falta un `CONTRIBUTING.md` y una política de versionado/flujo de ramas explícita

**Evidencia**
- `ls -a` no muestra `CONTRIBUTING.md`, `.editorconfig` ni `.pre-commit-config.yaml`; `RELEASE.md` describe tags pero no el flujo de ramas.
**Recomendación**
- Documento de 40 líneas: flujo de ramas usado (`master` es la rama de trabajo según `ci.yml`), convención de commits, cómo correr el gate, cómo añadir un ADR.

---

#### [BAJO] Observabilidad: `--health` no reporta versión, hash del commit, ni última ejecución con error

**Evidencia**
- `tukul_core/health.py` (179 líneas) informa config/logging/keyring, no build metadata.
**Recomendación**
- Añadir `version` (desde `importlib.metadata`) y `commit` (inyectado en build con una variable de entorno en PyInstaller). Es el dato que más se pide en un ticket de soporte.

---

## 4. Roadmap ejecutable (Paso 4)

### Fase 1 — Consistencia de la puerta de calidad (esta semana)

#### Tarea 1: Alinear `quality-gate.sh` con CI
- **Severidad:** ALTO · **Esfuerzo:** S · **Dependencias:** ninguna
- **Problema:** el gate local omite `pip-audit` y `bandit`, y falla en un checkout sin instalar.
- **Solución:** añadir pasos `pip_audit --local --skip-editable` y `bandit -r tukul_core tukul_ui -lll -ii`; comprobar `import tukul_core` antes de pytest con mensaje de instalación; añadir los `Verify health/config/CLI` del workflow al script y llamar al script desde CI (o mantener paridad con un comentario que lo exija en revisión).
- **Archivo(s):** `scripts/quality-gate.sh`, `.github/workflows/ci.yml`, `docs/TESTING.md`.
- **Verificación:** `bash scripts/quality-gate.sh` en un clon limpio sin `pip install -e .` imprime el mensaje de instalación y, tras `pip install -e ".[dev]"`, pasa de extremo a extremo.

#### Tarea 2: Diagnóstico de campos de perfil descartados
- **Severidad:** ALTO · **Esfuerzo:** S · **Dependencias:** ninguna
- **Problema:** `_coerce_profile_fields` descarta campos sin aviso.
- **Solución:** acumular descartes y `logger.warning` por campo; devolverlos en `load_profiles` (tupla extendida o dataclass `LoadedProfiles`) y mostrarlos en `--health`. Test: TOML con `max_output_tokens = 4096.0` → warning + perfil válido con 4096 o aviso explícito según la política elegida.
- **Archivo(s):** `tukul_core/storage.py`, `tukul_core/health.py`, `tests/test_core.py`.
- **Verificación:** `test_perfil_con_tipo_invalido_emite_diagnostico` pasa; `--health` con ese TOML lo imprime.

### Fase 2 — Corrección documental y contrato HTTP (próximas 2 semanas)

#### Tarea 3: Reconciliar la documentación de la fuente CVE
- **Severidad:** MEDIO · **Esfuerzo:** XS · **Dependencias:** ninguna
- **Solución:** borrar o convertir en histórico la sección "planeada" de `SECURITY.md`; fila en `TRACEABILITY.md`.
- **Archivo(s):** `docs/SECURITY.md`, `docs/TRACEABILITY.md`.
- **Verificación:** `grep -rn "prototipo aislado" docs/` → sin resultados; índice documental coherente.

#### Tarea 4: Tests de contrato HTTP para `LLMClient`
- **Severidad:** MEDIO · **Esfuerzo:** M · **Dependencias:** ninguna
- **Solución:** servidor local `http.server` con 4 escenarios (SSE, 429+Retry-After, 302 no seguido, body sobredimensionado) + 3 tests de cabeceras por protocolo.
- **Archivo(s):** `tests/test_llm_http_contract.py` (nuevo).
- **Verificación:** 7 tests verdes en < 3 s, cobertura de `llm.py` ≥ 90 %.

#### Tarea 5: Cancelación inmediata durante el backoff
- **Severidad:** MEDIO · **Esfuerzo:** XS · **Dependencias:** Tarea 4
- **Solución:** `cancel_event.wait(delay)` en `_open_with_retry`.
- **Archivo(s):** `tukul_core/llm.py`.
- **Verificación:** test que cancela durante un `429` y comprueba retorno < 100 ms.

### Fase 3 — Descomposición de la UI (4-8 semanas, incremental)

#### Tarea 6: Extraer `RequestLifecycle`
- **Severidad:** ALTO · **Esfuerzo:** L · **Dependencias:** Tareas 4 y 5
- **Solución:** nuevo módulo `tukul_ui/request_lifecycle.py` con `start/cancel/on_event`; sustituir los cuatro `def work` por llamadas; tests existentes (`test_cola_eventos`, `test_reentrada_peticiones`, `test_cierre_hilos`) deben pasar **sin cambios** como red de seguridad.
- **Archivo(s):** `tukul_ui/request_lifecycle.py` (nuevo), `tukul_ui/app.py`.
- **Verificación:** `app.py` < 2.300 líneas, cobertura del nuevo módulo ≥ 90 %, suite sin regresiones.

#### Tarea 7: Extraer `UIStateBookkeeper`
- **Severidad:** MEDIO · **Esfuerzo:** M · **Dependencias:** Tarea 6
- **Solución:** mover snapshot/saneado/poda/guardado de `estado.json`.
- **Verificación:** `test_estado_ui.py` y `test_ui_state.py` pasan sin cambios.

### Fase 4 — Pulido de calidad y entrega

#### Tarea 8: Accesibilidad determinista
- **Severidad:** MEDIO · **Esfuerzo:** M · **Dependencias:** ninguna
- **Solución:** tests de contraste WCAG, tabla `EstadoUI → estado_accesible`, foco de diálogos.
- **Verificación:** tests nuevos verdes bajo `xvfb-run`.

#### Tarea 9: Checksums + SBOM en release
- **Severidad:** MEDIO · **Esfuerzo:** S · **Dependencias:** ninguna
- **Solución:** `SHA256SUMS` y `sbom.cdx.json` como assets del tag.
- **Verificación:** descargar assets del tag de prueba y `sha256sum -c SHA256SUMS`.

---

## 5. Matriz de dependencias

| Tarea | Depende de | Bloquea a |
|---|---|---|
| 1 Gate | — | (reduce riesgo de todo lo demás) |
| 2 Perfiles | — | — |
| 3 Doc CVE | — | — |
| 4 Contrato HTTP | — | 5, 6 |
| 5 Cancelación | 4 | 6 |
| 6 RequestLifecycle | 4, 5 | 7 |
| 7 UIStateBookkeeper | 6 | — |
| 8 Accesibilidad | — | — |
| 9 Release | — | — |

---

## 6. Deuda técnica (orden de impacto)

1. `TukulApp` monolítico y duplicación del ciclo de petición (riesgo de regresión del tipo que ya ocurrió en 2026-11-02).
2. Divergencia gate local ↔ CI.
3. Coercición silenciosa de perfiles.
4. Cobertura E2E del cliente HTTP.
5. Referencia visual única y accesibilidad no verificada.
6. Documentación de la fuente CVE duplicada y contradictoria.
7. Checksums/SBOM y doble lockfile.

---

## 7. Quick wins (< 30 min cada uno)

- Convertir en histórico la sección "planeada" de `SECURITY.md` (Tarea 3).
- `cancel_event.wait(delay)` en `_open_with_retry` (Tarea 5).
- Añadir `pip_audit` + `bandit` al gate (Tarea 1).
- `--health` imprime `tukul __version__` (Tarea 10).
- Renombrar `test_auditoria_regresion.py` a un nombre que mencione su dominio real o dividir el archivo con `git mv` por clase.

---

## 8. Métricas de referencia (ejecución real del 2026-11-04)

| Métrica | Valor | Umbral / contrato |
|---|---|---|
| Tests | 425 passed, 1 failed (artefacto de instalación) | 0 fallos |
| Cobertura total | **81 %** | ≥ 70 % (CI) |
| Cobertura `app.py` | 74 % | objetivo 85 % tras Fase 3 |
| Cobertura `llm.py` | 83 % | objetivo 90 % tras Tarea 4 |
| ruff | 0 hallazgos | 0 |
| mypy | 0 errores / 42 archivos | 0 |
| Mayor archivo de producto | `tukul_ui/app.py` 3.085 líneas | objetivo < 1.500 |
| Mayor archivo de test | 1.427 líneas | objetivo < 600 |
| LOC producto / tests | ~7.700 / ~7.300 | — |
| Providers soportados | 3 protocolos, 3 entradas registradas | — |

---

## 9. Primera tarea a ejecutar

**Tarea 1 — alinear `scripts/quality-gate.sh` con CI y hacer que detecte el checkout sin instalar.**

Es de esfuerzo S, no depende de nada y elimina la clase de problema que hizo que esta auditoría encontrara un fallo local que CI no vería (y viceversa: dependencias vulnerables que solo CI detecta). Además convierte "el gate es el espejo de CI" en una afirmación verificable, que es la premisa sobre la que descansan todas las tareas siguientes.
