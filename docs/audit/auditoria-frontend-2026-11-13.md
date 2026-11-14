# Auditoría Frontend / UI — Tukul

**Fecha:** 2026-11-13
**Nivel:** Completo (repo maduro, entregable formal)
**Modo:** estático + comandos + evidencia de captura existente (sin navegador: es una app de escritorio Tkinter, no web)
**Alcance revisado:** toda la capa `tukul_ui/` (6 782 LOC, 24 módulos): `app.py`, `dialogs.py`, `contexto_dialogo.py`, `ideas.py`, `estado.py`, `ui_state.py`, `request_lifecycle.py`, `worker_threads.py`, `tooltip.py`, `estilo.py`, `tema.py`, `proyectos.py`, `document_manager.py`, `chunk_buffer.py`, `context_papproval.py`, `llm_session_manager.py`, `components/`.
**No revisado:** `tukul_core/` (backend puro, fuera del límite de esta skill), `docs/` como prosa, empaquetado PyInstaller, comportamiento en Windows/macOS (retirados por decisión de producto).
**Comandos ejecutados:** `ruff check .` · `mypy tukul_core tukul_ui tukul.py` · `xvfb-run pytest` (178 tests de UI + subset acotado) · `pytest --cov=tukul_ui`.

**Numeración de hallazgos:** `DF-001`…`DF-016` (contador reiniciado en esta auditoría con fecha, según [`CONTRIBUTING.md`](../../CONTRIBUTING.md#auditorías)). Al citarlos, incluir la fecha de este informe para evitar colisiones.

---

## 1. Resumen ejecutivo

El frontend está en **muy buen estado**: lint y tipado limpios (0 hallazgos), 178 pruebas de UI verdes, accesibilidad pensada de raíz (estados con símbolo+texto+color, tooltips que respetan el foco, atajos de teclado completos). No hay rutas rotas ni vulnerabilidades de cliente.

Los tres riesgos reales son de **mantenibilidad y robustez**, no de corrección inmediata:

1. **`TukulApp` es un god object** (2 657 líneas, 152 métodos, ~228 miembros, 19 responsabilidades). Bloquea la evolución y hace costoso cualquier cambio de UI.
2. **Fugas de hilo en los módulos satélite**: 6 llamadas `after(0, …)` desde workers sin la guarda que el propio `app.py` usa. En CPython 3.13 pueden abortar el proceso (el repo ya documentó y sufrió ese fallo).
3. **Los diálogos están poco cubiertos** (`ideas.py` 18 %, `contexto_dialogo.py` 38 %, `request_lifecycle.py` 41 %) y contienen una fuga real: `add_references` falla en silencio cuando todos los archivos son inválidos.

**Conteo por severidad:** Crítico 0 · Alto 3 · Medio 7 · Bajo 6 (16 hallazgos).

---

## 2. Alcance y métricas observadas

| Métrica | Valor | Método |
|---|---|---|
| LOC capa UI | 6 782 (24 módulos) | `wc -l` |
| `app.py` | 2 657 líneas · clase `TukulApp` 152 métodos | Serena AST |
| `ruff check .` | 0 hallazgos | CLI |
| `mypy tukul_core tukul_ui tukul.py` | 0 errores (25 archivos) | CLI |
| Tests UI ejecutados | 178 passed (79,7 s, xvfb) | pytest |
| Cobertura `tukul_ui` (subset UI) | 67 % total | pytest-cov |
| Cobertura por módulo débil | `ideas.py` 18 % · `request_lifecycle.py` 41 % · `contexto_dialogo.py` 38 % | pytest-cov |
| TODOs de código | 0 (los 3 matches de "TODO" son la palabra en español) | grep |
| `except:` desnudos | 0 | grep |

Nota operativa: la suite completa sin acotar llegó a consumir **22 GB de RSS** y quedarse en `R` durante >8 min en un runner de 16 GB antes de ser detenida. Los tests de UI pasan limpios cuando se ejecutan acotados; la causa de la avalancha no se aisló `[NO VERIFICADO]`.

---

## 3. Tabla de hallazgos

| ID | Sev. | Tipo | Ubicación | Resumen | Esf. | Certeza |
|---|---|---|---|---|---|---|
| DF-001 | Alto | Deuda técnica | `tukul_ui/app.py` (todo el archivo) | `TukulApp` god object: 2 657 líneas, 152 métodos, 19 responsabilidades | L | VERIFICADO |
| DF-002 | Alto | Riesgo | `contexto_dialogo.py:196,198,258,261,369,373`; `ideas.py:193`; `dialogs.py:329,460` | `after(0,…)` desde workers sin guarda; puede abortar el proceso (CPython 3.13) | M | VERIFICADO |
| DF-003 | Alto | Bug | `contexto_dialogo.py:131,138,507` | `add_references` falla en silencio si todos los archivos se descartan | S | VERIFICADO |
| DF-004 | Medio | Deuda técnica | `contexto_dialogo.py:455-463,292-298,390-396`; `ideas.py:262-271` | Setup de modal reimplementado 4× fuera de `_abrir_dialogo` | M | VERIFICADO |
| DF-005 | Medio | Deuda técnica | `dialogs.py:148-150`; `contexto_dialogo.py:443-446,557-559`; `ideas.py:445-451` | 4 copias literales del reaplicado de tema de `Listbox` | S | VERIFICADO |
| DF-006 | Medio | Deuda técnica | `dialogs.py:182-186`; `contexto_dialogo.py:305-312,403-410,478-483`; `ideas.py:286-302` | 5 copias de la misma configuración de `Listbox` (~8 kwargs) | S | VERIFICADO |
| DF-007 | Medio | Deuda técnica | `app.py:1749-1766` vs `1849-1875` | Validación de presupuesto de tokens duplicada en 2 flujos | M | VERIFICADO |
| DF-008 | Medio | Bug/UX | `dialogs.py:444` vs `:682` | Misma condición, dos mensajes distintos | S | VERIFICADO |
| DF-009 | Medio | Mejora | `dialogs.py:666-671,331` | "Probar conexión" sin estado de carga ni deshabilitado | S | VERIFICADO |
| DF-010 | Medio | Deuda técnica | `app.py:2333,2337,2373,2381,2390,2395,2416` | 7 métodos fachada sin ninguna referencia en el repo | S | VERIFICADO |
| DF-011 | Bajo | Bug/UX | `tooltip.py:75-84` | El tooltip recorta el borde vertical (solo espeja `x`) | S | VERIFICADO |
| DF-012 | Bajo | Mejora | `estado.py` / `estilo.py` hardcodes | Consistencia de copy: `artículo` vs `documento`, mayúsculas y puntos | S | VERIFICADO |
| DF-013 | Bajo | Deuda técnica | `app.py:2091-2105` | `history` sin tope de crecimiento; `streaming_text +=` por chunk | M | VERIFICADO |
| DF-014 | Bajo | Mejora | `dialogos.py` / `app.py` | `wraplength` fijos (300/320/380/520/580) sin helper común | S | VERIFICADO |
| DF-015 | Bajo | Mejora | `top_bar.py:100,118` | Botones símbolo-solo (`☰`) sin nombre accesible programático | S | VERIFICADO |
| DF-016 | Bajo | Deuda técnica | `app.py:367,370` | `_keys_llavero` escrito desde worker sin lock | S | VERIFICADO |

---

## 4. Detalle (Crítico y Alto)

### DF-001 — `TukulApp` es un god object
**Ubicación:** `tukul_ui/app.py:184` (clase), 2 657 líneas, 152 métodos, 19 clústeres de responsabilidad.
**Evidencia:** un solo `tk.Tk` mezcla ventana + DPI/geometría (`_ajustar_dpi:388`, `_restaurar_geometria:469`), sistema visual completo (`_aplicar_tema:506`, `_reaplicar_estilos_widgets:573`), credenciales/llavero (`_precargar_key:341`, `_esperar_key:1692`), ciclo de petición LLM (`request:1776`, `finish:1974`, `_dispatch_ui_event:2185`), autosave (`_write_autosave:1393`), indexado de memoria (`_autoindexar_memoria:1597`), contextos (facade `_contexto:2289`), ideas (`_ideas:2349`), proyectos, recientes, zoom/foco, y persistencia de estado. El `__init__` (187-306) declara a la vez widgets (191-195), estado de UI (217), perfiles (243), cachés de llavero (247-252) y 4 sub-controladores.
**Refutación intentada:** ¿es deuda aceptada? `pyproject.toml:135-142` admite que "la capa UI todavía no" tiene anotaciones y que exigirlas "obligaría a un refactor masivo fuera del alcance". Es decir, la deuda está reconocida, pero no hay ADR que fije un plan de extracción. No hay archivo `docs/decisions/` para el god object.
**Impacto:** cada cambio de UI toca un archivo de 2 657 líneas; el tipado estricto no se puede activar; los módulos ya extraídos (`request_lifecycle`, `ui_state`) demuestran que el camino existe pero se detuvo.
**Corrección:** extraer por responsabilidad siguiendo el patrón ya usado (`RequestLifecycle`, `ui_state`): (a) gestor de ventana/geometría/DPI/tema → `window_shell.py`; (b) credenciales/llavero → `credentials.py` (mover `_precargar_key`, `_esperar_key`, `_resolver_credenciales`); (c) autosave+stats → `editor_session.py`. Escribir un ADR que fije el objetivo y active `disallow_untyped_defs` para `tukul_ui` módulo a módulo.

### DF-002 — `after(0, …)` desde hilos worker sin guarda
**Ubicación:** `tukul_ui/contexto_dialogo.py:196,198` (threat feed), `:258,261` (memoria), `:369,373` (web búsqueda); `tukul_ui/ideas.py:193` (pipeline); `tukul_ui/dialogs.py:329` (probar conexión), `:460` (reindexar).
**Evidencia:** `contexto_dialogo.py:196` → `host.after(0, lambda: self.on_threat_feed_error(...))` ejecutado dentro de `work()`, que corre en `WorkerThreads.start` (`:200`). La única guarda es `if host.closing: return` (`:192`), que no cubre el `after` en sí. Contraste con el patrón correcto del propio `app.py`: `_autoindexar_memoria.work()` envuelve su `after` en `try/except (RuntimeError, tk.TclError)` (`app.py:1622-1626`), y `ideas.py:231` sí lo hace.
**Refutación intentada:** ¿el canal `control_queue` lo cubre? No — estos módulos llaman a `host.after` directamente, sin pasar por `control_queue`/`ChunkBuffer`. ¿Es teórico? No: `worker_threads.py:1-13` y `app.py:172-181` documentan que exactamente este caso abortó el proceso (`Fatal Python error: Aborted`) y se vio en `tests/test_llm_http_contract.py`.
**Impacto:** un worker `daemon` que sobreviva a `destroy()` puede llamar a `after()` sobre un intérprete Tcl sin bucle principal y abortar el proceso en vez de registrar un error. Ruta probable: cerrar la app con una búsqueda en memoria o una consulta de threat feed en vuelo.
**Corrección:** envolver cada `host.after(0, …)` en `try/except (RuntimeError, tk.TclError)` o, preferible, publicar el resultado por el canal existente (`control_queue`) y dejar que el bombeo de UI (`process_ui_events`) lo despache en el hilo correcto. Extraer un helper único `_en_hilo_ui(host, fn)` en `worker_threads.py` y usarlo en los 4 módulos.

### DF-003 — `add_references` falla en silencio
**Ubicación:** `tukul_ui/contexto_dialogo.py:131,138,507`.
**Evidencia:** el bucle descarta lo no-archivo (`if not path.is_file(): continue`, `:131`) y traga `OSError` (`except OSError: continue`, `:138`); el resultado solo se anuncia `if count:` (`:507`). Si el usuario selecciona solo archivos ilegibles/borrados, `count == 0` y **no se muestra ningún mensaje**: el diálogo parece no reaccionar.
**Refutación intentada:** ¿hay un mensaje previo en la llamada? `_add_references` (`app.py:2404`) delega sin validar; el `if count:` es la única salida.
**Impacto:** el usuario cree que la acción se ignoró; no sabe si el archivo era inválido, ilegible o demasiado grande.
**Corrección:** cuando `count == 0` y se seleccionó al menos un archivo, mostrar `messagebox.showwarning("Contexto de artículos", "No se añadió ningún archivo: no era legible o ya no existe.")`.

---

## 5. Detalle (Medio y Bajo) — resumen accionable

- **DF-004/005/006 (duplicación de diálogos):** cuatro modales (`dialogo de revisión` la excepción) repiten a mano `tk.Toplevel` + `title/transient/configure/minsize/geometry`; cuatro copias del reaplicado de tema de `Listbox`; cinco copias de la misma config de `Listbox`. **Corrección:** mover `_abrir_dialogo`, `_reaplicar_tema_listbox` y `_crear_listbox` a un módulo compartido (`dialogs_base.py`) y usarlos en `contexto_dialogo.py`, `ideas.py` y `dialogs.py`. Refutación: son tan idénticas que el riesgo de divergir ya se materializó (dos mensajes distintos para la misma condición, DF-008).
- **DF-007:** el bloque "estimar tokens → comparar con el techo → `_abort_request` + `show_error`" existe dos veces (`_solicitar_revision:1749` y `confirm_and_send:1849`). Extraer `_verificar_presupuesto(tokens, techo) -> bool`.
- **DF-008:** `"La carpeta indicada no existe."` (`dialogs.py:444`) y `"La carpeta de artículos indicada no existe."` (`dialogs.py:682`) describen la misma condición. Unificar.
- **DF-009:** "Probar conexión" lanza un hilo (`dialogs.py:331`) sin deshabilitar el botón ni mostrar progreso; el usuario puede pulsar varias veces y no ve nada hasta el final. Deshabilitar el botón y usar el `hint` ya existente (`:522`) para "Comprobando…".
- **DF-010:** 7 métodos fachada sin referencia repo-wide (verificado con grep: 0 refs cada uno): `_on_threat_feed_error:2333`, `_on_threat_feed_ready:2337`, `_registrar_error_ideas:2373`, `_show_idea_selection_dialog:2381`, `_reaplicar_tema_ideas:2390`, `_on_impact_suggestion_error:2395`, `_reaplicar_tema_contexto:2416`. Refutación: podrían ser API externa. Pero `docs/decisions/ADR-0004` ya fija la política para código huérfano ("dueño y motivo documentados o se elimina"); estos no la cumplen. **Corrección:** eliminarlos o documentarlos como API pública en un ADR.
- **DF-011:** el tooltip espeja `x` contra el borde derecho (`tooltip.py:82-83`) pero nunca limita `y` (`:76`), así que un control pegado abajo (compositor, `assistant_panel.py:48,76,89`) dibuja la pista fuera de pantalla. Añadir el mismo clamp para `y` con `winfo_screenheight()`.
- **DF-012:** copy inconsistente: `TEXTO_SIN_DOCUMENTO = "Sin artículo abierto"` en un widget `documento_label` cuyo tooltip dice `"Documento activo"` (`top_bar.py:34,153,156`) mientras el resto usa "artículo" (`top_bar.py:161-162`); títulos en Title Case vs Sentence case; `"Probar conexión"`/`"Reindexar"` sin `…` pese a ser operaciones largas mientras otras sí lo llevan. Definir un glosario corto (¿"artículo" o "documento"?) y aplicarlo.
- **DF-013:** el widget `history` no tiene tope de líneas (solo `clear_history` manual, `app.py:1173`) y `streaming_text += value` (`:2101`) re-crea la cadena por chunk. Refutación: el techo de memoria real lo impone `LLMSessionManager._accept_chunk` (contador O(1), `llm_session_manager.py:104-132`), así que no es O(n²) confirmado. Aun así, sesiones muy largas hacen crecer el widget sin límite. Considerar truncado por número de turnos.
- **DF-014:** `wraplength` fijos y dispares (300/320/380/520/580) inline en `dialogs.py`, `ideas.py`, `contexto_dialogo.py`, `assistant_panel.py`. `assistant_panel.py:141-147` ya tiene la lógica de ajuste dinámico: reutilizarla.
- **DF-015:** `boton_menu` usa solo `"☰"` (`top_bar.py:100`) y `boton_tema` nace sin texto (`:118`); en Tk el nombre accesible es el `text`, y el tooltip no lo sustituye. Añadir texto/`text=` legible o exponer el nombre por otra vía.
- **DF-016:** `_precargar_key.leer()` escribe `self._keys_llavero[perfil]` y `self._llaves_en_curso.pop(...)` desde un hilo (`app.py:367,370`) sin lock, mientras `key` (`:326`) los lee en el hilo de Tk. Bajo el GIL cada op es atómica, pero es estado mutable compartido sin sincronizar; un `dict` + `threading.Lock` o `queue` lo cierra.

---

## 6. Roadmap priorizado

**Inmediato (esta semana, S–M):**
- DF-003 (silencio en `add_references`) — bug visible, arreglo de 3 líneas.
- DF-002 (guardas de `after`) — riesgo de aborto de proceso; helper único + 6 puntos.
- DF-008 y DF-009 — microcorrecciones de copy y feedback en diálogos.

**Corto plazo (2–4 semanas, M):**
- DF-004/005/006 → `dialogs_base.py` compartido (habilita además DF-014 y DF-008).
- Cobertura: subir `ideas.py`, `contexto_dialogo.py`, `request_lifecycle.py` (hoy 18/38/41 %).
- DF-010 → decidir por método: borrar o documentar con ADR siguiendo ADR-0004.
- DF-016 → sincronizar el caché de llavero.

**Estructural (trimestre, L):**
- DF-001 → descomponer `TukulApp` por el patrón ya probado y activar tipado estricto en `tukul_ui` por módulos; acompañar con ADR.
- DF-013 → política de retención del historial de chat.
- Investigar la avalancha de memoria de la suite completa (bloquea la confianza en el pipeline).

**Dependencias:** DF-014 y DF-008 dependen de DF-004/005 (base común de diálogos). DF-001 es independiente pero habilita el resto al bajar el coste de tocar UI.

---

## 7. Preguntas abiertas / información faltante

1. **Glosario de producto:** ¿el objeto se llama "artículo" o "documento"? (afecta DF-012 y toda la copy).
2. **God object:** ¿existe ya un plan/ADR de troceado de `TukulApp` o DF-001 es deuda sin dueño? No encontré ADR al respecto.
3. **`ideas.py`:** ¿es una función estable o experimental? Su 18 % de cobertura y su ausencia en el README sugieren que podría no estar en el flujo principal.
4. **Suite completa:** ¿la avalancha de 22 GB es reproducible en CI con el runner real (timeout 120 s/test) o solo aparece en este host? `[NO VERIFICADO]`.

## 8. Límites

- No se ejecutó la app con interacción humana real; la evidencia visual proviene de `docs/screenshots/tukul.png` (captura del 2026-11-12), no de una sesión nueva `[NO VERIFICADO]` para estados posteriores.
- El análisis de comportamiento se basa en strings y estructura de widgets, no en observación de usuarios.
- Dependencias (versiones/CVEs) no auditadas aquí: fuera del límite de esta skill (ver `pip-audit` del gate).
- `tukul_core` excluido por diseño.
