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
2. **Ventana / DPI / geometría / tema → `tukul_ui/window_shell.py`** — PENDIENTE.
   Mover `_ajustar_dpi`, `_aplicar_tamano_inicial`, `_restaurar_geometria`,
   `_ventana_mapeada`, `_tema_validado`, `_theme` y `_reaplicar_estilos_widgets`.
   La lógica pura ya vive en `tukul_ui/ventana.py`; aquí queda solo lo que toca
   Tk.
3. **Autosave + estadísticas → `tukul_ui/editor_session.py`** — PENDIENTE.
   Mover `_write_autosave`, el temporizador `autosave_after` y el cálculo de
   estadísticas del documento.

Tras cada extracción, `tukul_ui` pasa a exigir `disallow_untyped_defs` módulo a
módulo (empezando por los ya extraídos), en lugar de relajar la regla para toda
la capa.

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
  retirarse cuando no queden consumidores que usen el estado interno del store.
- DF-001 queda **parcialmente cerrado** en este ciclo: el criterio de cierre
  (`app.py < 2 300`) no se alcanza aún, así que el hallazgo **sigue abierto**
  hasta completar los pasos 2 y 3.

## SECURITY_IMPACT

El manejo de credenciales se centraliza en un único objeto con su lock, lo que
reduce el riesgo de carrera ya señalado (DF-016). No cambia el modelo de
almacenamiento (llavero del SO) ni la política de secretos.

## TESTING_IMPACT

`CredentialStore` se prueba con un lanzador de hilos y un avisador dobles:
precedencia de `resolver_key`, caché de solo lectura, backend ausente y
`esperar` con tope. Los tests existentes que tocan `_keys_llavero` /
`_llaves_en_curso` siguen funcionando por las *properties* de compatibilidad.
