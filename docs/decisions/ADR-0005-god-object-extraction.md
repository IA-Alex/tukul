# ADR-0005: extracción por responsabilidades de `TukulApp`

STATUS: Accepted

## CONTEXT

La auditoría frontend del 2026-11-13
(`docs/audit/auditoria-frontend-2026-11-13.md`, DF-001) confirmó que `TukulApp`
es un *god object*: 2 657 líneas y 152 métodos que mezclan ventana, DPI y
geometría, sistema visual, credenciales/llavero, ciclo de petición LLM,
autosave, indexado de memoria, contextos, ideas, proyectos, recientes, zoom y
persistencia de estado en una sola clase.

`pyproject.toml` reconoce la deuda ("la capa UI todavía no" tiene anotaciones
estrictas), pero **no había un ADR que fijara un plan de extracción**: el
refactor se había detenido tras `RequestLifecycle` y `ui_state`. Sin un plan
documentado, cualquier cambio de UI toca un archivo de más de 2,5 mil líneas y
el tipado estricto no se puede activar.

## DECISION

Se extrae `TukulApp` **por responsabilidades**, siguiendo el patrón ya probado
en el repo (objeto inyectado, contrato estrecho, host dueño de su estado) y de
menor a mayor riesgo. El objetivo de cierre es `tukul_ui/app.py` **< 2 300
líneas** y cobertura del módulo extraído **≥ 90 %**.

Orden acordado:

1. **Credenciales / llavero → `tukul_ui/credentials.py`** — HECHO en este ciclo.
   `CredentialStore` es dueño de la caché del llavero y de su
   `threading.Lock`; `resolver_key` fija el orden de precedencia
   (entorno > sesión > llavero). Resuelve además DF-016 (estado mutable
   compartido sin sincronizar). `TukulApp` conserva `_keys_llavero` y
   `_llaves_en_curso` como *properties* de compatibilidad hacia el store, para
   no romper a `dialogs.py` ni a los tests que los consumen.
2. **Ventana / DPI / geometría / tema → `tukul_ui/window_shell.py`** — HECHO.
   `WindowShell` es dueño del tema activo y del acceso a Tk para
   `ajustar_dpi`, `aplicar_tamano_inicial`, `restaurar_geometria`,
   `ventana_mapeada` y `saneada_actual`; la política de persistencia (no
   guardar una ventana sin mapear) se queda en el host. La lógica pura sigue en
   `tukul_ui/ventana.py`. `TukulApp` conserva delegaciones (`_ajustar_dpi`,
   `_aplicar_tamano_inicial`, `_restaurar_geometria`, `_ventana_mapeada`,
   `_theme`, `_tema_validado`, `PATRON_GEOMETRIA` y saneadores) y `theme` se
   mantiene sincronizado desde `_aplicar_tema`.
3. **Autosave + estadísticas → `tukul_ui/editor_session.py`** — HECHO.
   `EditorSession` es dueño de `autosave_after` y `stats_after`, de la
   escritura del respaldo (`write_autosave`) y del cálculo de métricas del pie.
   `TukulApp` conserva `_schedule_autosave`, `_write_autosave`,
   `_clear_current_autosave`, `schedule_stats` y `update_stats` como
   delegaciones, y expone ambos temporizadores como *properties* de
   compatibilidad. `destroy()` delega la cancelación en
   `cancelar_temporizadores()`.

Tras cada extracción, `tukul_ui` pasa a exigir `disallow_untyped_defs` módulo a
módulo (empezando por los ya extraídos), en lugar de relajar la regla para toda
la capa.

### Nota sobre el criterio de cierre de líneas

El objetivo de `app.py < 2 300` líneas **no se cumple por sí solo al extraer**:
las delegaciones y *properties* de compatibilidad mantienen la API histórica
que consumen los tests y otros módulos, y eso deja `app.py` en ~2 610 líneas.
DF-001 se cierra **por responsabilidades** (la lógica vive en módulos con
contrato propio y cobertura propia) y la métrica de líneas se reevalúa cuando se
retiren los *shims* de compatibilidad, que es un trabajo aparte y con su propio
riesgo (romper a los consumidores).

## ALTERNATIVES

- **No tocar `TukulApp`**: la deuda sigue bloqueando cualquier cambio de UI y
  el tipado estricto. Descartada.
- **Reescribir la UI desde cero**: riesgo desproporcionado y rompe contratos
  probados. Descartada.
- **Extraer todo en un solo refactor**: mezcla decisiones independientes y hace
  imposible un `git bisect` limpio. Descartada.

## CONSEQUENCES

- El coste de tocar UI baja con cada módulo extraído; los cambios quedan
  revisables por separado.
- Se introducen *properties* de compatibilidad temporales en `TukulApp`; deben
  retirarse cuando no queden consumidores que usen el estado interno de los
  objetos extraídos.
- DF-001 queda **cerrado por responsabilidades**: ventana (`window_shell.py`),
  credenciales (`credentials.py`) y autosave/estadísticas (`editor_session.py`)
  tienen contrato propio y cobertura propia. El criterio de `app.py < 2 300`
  líneas depende de retirar los *shims* de compatibilidad (ver la nota en
  DECISION), no de completar más extracciones.

## SECURITY_IMPACT

El manejo de credenciales se centraliza en un único objeto con su lock, lo que
reduce el riesgo de carrera ya señalado (DF-016). No cambia el modelo de
almacenamiento (llavero del SO) ni la política de secretos. `WindowShell` y
`EditorSession` no tocan secretos: solo presentación de ventana y autosave del
documento.

## TESTING_IMPACT

`CredentialStore` se prueba con un lanzador de hilos y un avisador dobles:
precedencia de `resolver_key`, caché de solo lectura, backend ausente y
`esperar` con tope. `WindowShell` (`tests/test_window_shell.py`) y
`EditorSession` (`tests/test_editor_session.py`) se prueban con hosts mínimos
que registran `after`/`after_cancel`, sin montar la aplicación completa. Los
tests existentes que tocan `_keys_llavero`, `_llaves_en_curso`, `autosave_after`
o `stats_after` siguen funcionando por las *properties* de compatibilidad.
