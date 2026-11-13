# Auditoría de Naming: Renombre `articulador` → `Tukul`

> **Estado:** COMPLETADO — Hallazgos corregidos  
> **Fecha:** 29/9/2026  
> **Auditor:** Arquitectura / Calidad  
> **Propósito:** Validar que el renombre de la carpeta del workspace (contenedor físico)
> de `articulador` a `Tukul` no introdujo inconsistencias, y que el naming del
> proyecto es uniforme en todas las capas del sistema.

---

## Resumen ejecutivo

El cambio de carpeta del workspace de `articulador` a `Tukul` es **correcto y
deseable**: alinea el nombre del directorio con la identidad actual del proyecto.
El **impacto real es bajo** porque el código fuente no depende de rutas absolutas
de la carpeta contenedora (usa `Path.home()` y rutas relativas).

Se identificaron **6 hallazgos**, de los cuales **2 son críticos** (settings de
Claude con rutas absolutas obsoletas), **1 es moderado** (test de performance
nunca migrado) y **3 son menores**. El resto del sistema está consistente.

---

## Ámbito de la auditoría

- **95+ archivos** analizados en el workspace
- Código fuente Python (`tukul_core/`, `tukul_ui/`, `tukul.py`)
- Configuraciones de herramientas (`.claude/`, `.codex/`, `.agents/`)
- CI/CD (`.github/workflows/`)
- Documentación (`docs/`, `README.md`, `CHANGELOG.md`)
- Lock files y empaquetado (`requirements-dev.lock`, `pyproject.toml`)
- Assets (`articulador.png`)
- Rutas de sistema, keyring, logging

---

## Línea base: lo que ya estaba correcto

El proyecto ya había pasado por un renombre interno completo (documentado en
`docs/SESSION_CONTINUITY.md`). La carpeta del workspace era el último elemento
que no coincidía.

| Componente | Antes | Ahora | Archivo de referencia |
|---|---|---|---|
| Paquete PyPI | `articulador` | `tukul` | `pyproject.toml:2` |
| Paquetes de código | `articulador_core/`, `articulador_ui/` | `tukul_core/`, `tukul_ui/` | Sistema de archivos |
| Clase principal | `ArticuladorApp` | `TukulApp` | `tukul_ui/app.py:92` |
| Título de ventana | `"Articulador"` | `"Tukul"` | `tukul_ui/app.py:97` |
| Logger | `"articulador"` | `"tukul"` | `tukul_core/logging_config.py:9` |
| Ruta de log | `~/.local/state/articulador/articulador.log` | `~/.local/state/tukul/tukul.log` | `tukul_core/logging_config.py:10` |
| Ruta de config | `~/.config/articulador/config.toml` | `~/.config/tukul/config.toml` | `tukul_core/storage.py:33` |
| Ruta de autosave | `~/.local/state/articulador/autosave` | `~/.local/state/tukul/autosave` | `tukul_core/autosave.py:16` |
| Ruta de feed cache | *(no existía)* | `~/.local/state/tukul/feed_cache` | `tukul_ui/app.py:67` |
| Keyring service | `"articulador"` | `"tukul"` | `tukul_core/storage.py:243,253,263` |
| Comando CLI | *(no existía)* | `tukul` | `pyproject.toml:44` |
| Entry point | `articulador.py` | `tukul.py` | Raíz del proyecto |
| Extensión proyectos | `*.articulador.json` | `*.tonal.json` | `tukul_ui/document_manager.py` |
| CI/CD workflows | `articulador_core`, `articulador_ui` | `tukul_core`, `tukul_ui` | `.github/workflows/ci.yml` |
| Build releases | `articulador-linux-x86_64`, etc. | `tukul-linux-x86_64`, etc. | `.github/workflows/build-release.yml` |
| URL de repositorio | *(no aplica)* | `github.com/IA-Alex/tukul` | `pyproject.toml:27` |
| Display name (UI) | `"Articulador"` | `"Tukul"` | `tukul_ui/app.py` |
| System prompt LLM | `"Articulador"` | `"Tukul"` | `tukul_core/llm.py` |


---

## Hallazgos

### 🔴 CRÍTICO — Hallazgo 1: `.claude/settings.json` con rutas absolutas obsoletas

**Archivo:** `/home/panda/Tukul/.claude/settings.json`

**Problema:** El archivo contiene reglas de permiso con la ruta absoluta del
workspace anterior:

```json
"Bash(chmod +x /home/panda/Articulos/articulador/scripts/quality-gate.sh)",
"Bash(/home/panda/Articulos/articulador/scripts/quality-gate.sh)"
```

Además hay decenas de entradas con rutas temporales que incluyen
`-home-panda-Articulos-articulador-` en rutas de scratchpad (ya eliminados).

**Impacto:** Los comandos que referencian directamente
`/home/panda/Articulos/articulador/` fallarán con error de ruta no encontrada si
Claude intenta ejecutarlos.

**Prioridad:** INMEDIATA


---

### 🔴 CRÍTICO — Hallazgo 2: `.claude/settings.local.json` con ruta absoluta obsoleta

**Archivo:** `/home/panda/Tukul/.claude/settings.local.json`

**Problema:**

```json
"Bash(python3 -m py_compile /home/panda/Articulos/articulador/tukul.py
       /home/panda/Articulos/articulador/tukul_core/*.py
       /home/panda/Articulos/articulador/tukul_ui/*.py)"
```

**Impacto:** El comando no encontrará los archivos en la ruta antigua.

**Prioridad:** INMEDIATA

---

### 🟡 MODERADO — Hallazgo 3: `tests/performance/locustfile.py` sin migrar

**Archivo:** `/home/panda/Tukul/tests/performance/locustfile.py`

**Problema:** Este archivo nunca fue actualizado durante el renombre del proyecto.
Contiene:

| Línea | Elemento | Valor actual | Valor esperado |
|---|---|---|---|
| 4 | Env var en docstring | `ARTICULADOR_LOAD_HOST` | `TUKUL_LOAD_HOST` |
| 5 | Env var en docstring | `ARTICULADOR_LOAD_API_KEY` | `TUKUL_LOAD_API_KEY` |
| 15 | Nombre de clase | `TonalLlmUser` | `TukulLlmUser` |
| 25 | Env var en payload | `ARTICULADOR_LOAD_MODEL` | `TUKUL_LOAD_MODEL` |
| 35 | Env var en headers | `ARTICULADOR_LOAD_API_KEY` | `TUKUL_LOAD_API_KEY` |

Además, la clase usa `Tonal` (otro nombre intermedio del proyecto) que también
fue migrado a `Tukul`.

**Impacto:** Si alguien ejecuta esta prueba de carga, las variables de entorno no
se leerán correctamente a menos que el usuario exporte manualmente las variables
con el nombre antiguo.

**Prioridad:** ALTA


### 🟢 BAJO — Hallazgo 4: Docstring en `tukul_ui/estilo.py`

**Archivo:** `/home/panda/Tukul/tukul_ui/estilo.py` (línea 1)

**Problema:**

```python
"""Sistema visual de Articulator: precisión, estructura y foco."""
```

El nombre `Articulator` (inglés de "Articulador") sobrevive en el docstring del
módulo de estilo visual.

**Impacto:** Solo documentación. No afecta ejecución, compilación ni
comportamiento.

**Prioridad:** BAJA

---


---

### 🟢 BAJO — Hallazgo 5: Comentario generado en `requirements-dev.lock`

**Archivo:** `/home/panda/Tukul/requirements-dev.lock` (línea 65)

**Problema:**

```
# via articulador (pyproject.toml)
```

Este comentario fue generado por `uv` o `pip-compile` cuando `pyproject.toml`
aún tenía `name = "articulador"`. Se regenera automáticamente al ejecutar
`uv lock` o `pip-compile`.

**Impacto:** Cero en ejecución. El lock file sigue siendo funcional.

**Prioridad:** BAJA (se limpia solo con el próximo `uv lock`)

---

### 🟢 INOCUO — Hallazgo 6: `articulador.png` en la raíz

**Archivo:** `/home/panda/Tukul/articulador.png`

**Problema:** Archivo PNG con el nombre antiguo del proyecto presente en la raíz.

**Contexto:** El `.gitignore` ignora `tukul.png` (no `articulador.png`). No hay
referencias activas a este archivo en el código fuente ni en la documentación
vigente.

**Impacto:** Ninguno. Archivo huérfano.

**Prioridad:** OPCIONAL (se puede eliminar o renombrar)


---

### ✅ INOCUOS — Documentos de archivo e históricos

Los siguientes archivos contienen referencias al nombre antiguo pero están
marcados como HISTORICAL o ARCHIVE y su contenido es intencional:

| Archivo | Referencia | Razón |
|---|---|---|
| `docs/archive/NEXT_STEPS.md:19` | `cd /home/panda/Articulos/tonal` | Documento archivado con advertencia explícita |
| `docs/archive/MATURITY_REPORT.md:146` | `"logger": "tonal"` | Ejemplo en documento archivado |
| `docs/archive/INFORME_CORRECCIONES.md:175` | `"*.tonal.json"` | Código de ejemplo en documento archivado |
| `CHANGELOG.md:113` | `"Articulator"` en v0.2.0 | Entrada histórica del changelog |
| `docs/SESSION_CONTINUITY.md` | Múltiples referencias | Documenta el propio proceso de renombre |

**Veredicto:** ✅ INOCUOS — Deben conservarse como están.



---

## Matriz de impacto

| # | Hallazgo | Archivo | Tipo | Impacto | Prioridad |
|---|---|---|---|---|---|
| 1 | Ruta absoluta obsoleta | `.claude/settings.json` | Config IDE | 🔴 Alto | **INMEDIATA** |
| 2 | Ruta absoluta obsoleta | `.claude/settings.local.json` | Config IDE | 🔴 Alto | **INMEDIATA** |
| 3 | Env vars / clase con nombre antiguo | `tests/performance/locustfile.py` | Código fuente | 🟡 Medio | **ALTA** |
| 4 | Docstring con nombre antiguo | `tukul_ui/estilo.py` | Código fuente | 🟢 Bajo | **BAJA** |
| 5 | Comentario de lock generado | `requirements-dev.lock` | Lock file | 🟢 Bajo | **BAJA** |
| 6 | Asset PNG huérfano | `articulador.png` | Asset | 🟢 Ninguno | **OPCIONAL** |
| 7-11 | Docs de archivo / históricos | Varios en `docs/` | Documentación | ✅ Inocuo | **NINGUNA** |

---

## Recomendaciones

### Corrección inmediata (hallazgos 1-2)

Actualizar las rutas absolutas en los settings de Claude:

```bash
# En .claude/settings.json y .claude/settings.local.json
# Reemplazar todas las ocurrencias de:
/home/panda/Articulos/articulador/
# Por:
/home/panda/Tukul/
```

Alternativamente, eliminar las entradas obsoletas si los comandos ya no se usan.

### Corrección programada (hallazgo 3)

En `tests/performance/locustfile.py`:

| Actual | Reemplazar por |
|---|---|
| `ARTICULADOR_LOAD_HOST` | `TUKUL_LOAD_HOST` |
| `ARTICULADOR_LOAD_API_KEY` | `TUKUL_LOAD_API_KEY` |
| `ARTICULADOR_LOAD_MODEL` | `TUKUL_LOAD_MODEL` |
| `class TonalLlmUser` | `class TukulLlmUser` |

### Corrección menor (hallazgo 4)

En `tukul_ui/estilo.py:1`:

```python
# Actual:
"""Sistema visual de Articulator: precisión, estructura y foco."""

# Propuesto:
"""Sistema visual de Tukul: precisión, estructura y foco."""
```

### Limpieza opcional (hallazgos 5-6)

- Regenerar lock file: `uv lock`
- Eliminar o renombrar `articulador.png`



---

## Validación de consistencia de naming

Se verificó la consistencia del nombre `Tukul` en todas las capas del sistema:

| Capa | ¿Consistente? | Evidencia |
|---|---|---|
| Código fuente (paquetes, clases, módulos) | ✅ | `tukul_core/`, `tukul_ui/`, `TukulApp` |
| Interfaz de usuario (título, burbujas, status) | ✅ | `self.title("Tukul")` |
| CLI y entry point | ✅ | `tukul` como comando, `tukul.py` como script |
| Logging (logger name, ruta de archivo) | ✅ | `"tukul"`, `~/.local/state/tukul/tukul.log` |
| Configuración (ruta de archivo) | ✅ | `~/.config/tukul/config.toml` |
| Keyring (service name) | ✅ | `"tukul"` en `get_password`/`set_password` |
| Persistencia (estado, autosave, feed cache) | ✅ | `estado.json`, `autosave/`, `feed_cache/` |
| CI/CD (workflows, job names, artifacts) | ✅ | `tukul-linux-x86_64` |
| Empaquetado (PyPI, pyproject.toml) | ✅ | `name = "tukul"` |
| Documentación normativa | ✅ | `README.md`, `docs/ARCHITECTURE.md`, etc. |
| URLs y metadata | ✅ | `github.com/IA-Alex/tukul` |

**Conclusión de naming:** El nombre `Tukul` es consistente en todas las capas
activas del sistema. No hay fugas del nombre `articulador` en lógica de
producción, persistencia, red, interfaz de usuario, logging o empaquetado.

---

## Historial

| Fecha | Versión | Cambio |
|---|---|---|
| 29/9/2026 | 1.0 | Auditoría inicial posterior al renombre de carpeta del workspace |
| 29/9/2026 | 1.1 | Corrección de los 6 hallazgos: settings de Claude, locustfile, estilo.py, lock file, PNG obsoleto |

