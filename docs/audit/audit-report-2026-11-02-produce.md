# Auditoría Full-Stack — Articulador

**Fecha:** 2026-11-02
**Commit auditado:** `8d45cf7` (`fix: improve UX accessibility and responsive dialogs`) **+ cambios sin commit**
**Auditor:** arquitectura de software Sr. (skill `audit-fullstack`, asistida con Serena para navegación simbólica)
**Ámbito:** todo el repositorio (código, tests, CI, documentación, empaquetado)

---

## 1. Resumen ejecutivo

### Veredicto: 🔴 **NO ENTREGABLE — el producto no arranca en el estado actual del árbol de trabajo**

El repositorio **no se puede ejecutar ni probar**. Hay un refactor de reubicación de paquetes a medio hacer, **sin commitear**, que deja el código en un estado que no importa:

- 11 módulos de `articulador_core/` fueron **borrados** del working tree y copiados a `articulador_ui/articulador_core/`.
- **Ningún import fue actualizado**: hay **143 referencias** a `articulador_core` que ya no resuelven.
- Consecuencias verificadas:
  - `python articulador.py --health` → `ModuleNotFoundError: No module named 'articulador_core'`
  - `pytest` → `collected 0 items / 1 error` (**0 tests ejecutados** de ~4.900 líneas de tests)
  - `mypy` → `Cannot read file 'articulador_core'`
  - `ruff` → 2 errores nuevos (el código movido ya no respeta `per-file-ignores`)
  - `pyproject.toml` sigue declarando `packages = ["articulador_core", "articulador_ui"]` con el backend `setuptools.build_meta` (el `-e .` instalado localmente enmascara el fallo; CI puro fallaría).

**La buena noticia:** por debajo del estado roto, la base técnica es notablemente sólida para un proyecto de este tamaño. La escritura atómica es correcta, no se siguen redirects en llamadas autenticadas, las API keys no se serializan a disco, el modelo de hilos de la UI respeta Tkinter (los workers nunca tocan widgets), y hay puertas de calidad reales en CI. El trabajo pendiente es mayoritariamente **de arquitectura y operación**, no de rescate.

### Conteo de hallazgos

| Severidad | Cantidad |
|---|---|
| 🔴 CRÍTICO | 1 |
| 🟠 ALTO | 5 |
| 🟡 MEDIO | 10 |
| 🔵 BAJO | 9 |
| **Total** | **25** |

> Nota de calibración: el riesgo de seguridad absoluto es bajo (app local, sin servidor). Un hallazgo es CRÍTICO cuando **impide entregar**; "ALTO" aquí significa bloqueante o degradante grave, no explotable en remoto.

---

## 2. Contexto del repositorio (Paso 1)

| Dimensión | Valor |
|---|---|
| **Propósito** | Editor conversacional local de artículos Markdown con LLM remoto opcional |
| **Tipo** | Aplicación de escritorio (CLI de una orden + ventana Tkinter). **No es web, no hay backend servidor** |
| **Stack** | Python ≥3.11 (probado en 3.11/3.12/3.13), Tkinter, `urllib`, `tomli-w`, `keyring` (extra) |
| **Persistencia** | Archivos locales: `config.toml`, `estado.json`, autosave, proyectos JSON. **Sin base de datos** |
| **Infra** | GitHub Actions (CI + build-release con PyInstaller para Linux/Windows) |
| **Tamaño** | ~5.100 LOC de producto, ~4.900 LOC de tests, 14 módulos de producto |
| **Madurez** | v0.3.2 con tags publicados, CHANGELOG Keep-a-Changelog, ADRs, docs operativas |
| **Estado** | Árbol de trabajo **roto** (refactor sin commit); último commit verde era `8d45cf7` |

**Adaptación del eje "Backend/API":** al no existir servidor, se audita el **cliente HTTP (`LLMClient`)** y los **adaptadores de proveedor** como equivalente de backend: contratos, validación, resiliencia y seguridad de egress.

---

## 3. Hallazgos

### 🔴 CRÍTICO

#### C-1. El árbol de trabajo no importa: reubicación de `articulador_core` incompleta y sin commitear

**Descripción**
Los 11 módulos de `articulador_core/` se copiaron a `articulador_ui/articulador_core/` y se borraron los originales, pero ni los imports, ni `pyproject.toml`, ni CI, ni los tests fueron actualizados. Recargar desde cero cualquier punto de entrada falla.

**Evidencia**
```
$ git status --short
 D articulador_core/__init__.py
 D articulador_core/autosave.py
 ... (11 archivos)
?? articulador_ui/articulador_core/

$ python articulador.py --health
  File ".../articulador.py", line 10, in <module>
    from articulador_core import storage
ModuleNotFoundError: No module named 'articulador_core'

$ xvfb-run -a python -m pytest -q
collected 0 items / 1 error
E   ModuleNotFoundError: No module named 'articulador_core'   (tests/test_auditoria_regresion.py:32)

$ python -m mypy articulador_core articulador_ui articulador.py
mypy: error: Cannot read file 'articulador_core': No such file or directory

$ python -m ruff check .
Found 2 errors.   (RUF001 en articulador_core/logging_config.py, C901 show_review_dialog)
```

Contraste: `artikulador_ui/app.py:15` sigue diciendo `from articulador_core import storage`, y `pyproject.toml` conserva:

```toml
[tool.setuptools]
packages = ["articulador_core", "articulador_ui"]
```

El inicio `-e .` presente en `.venv` hace que **localmente parezca instalado** (el `.pth` apunta a la raíz), lo que explica por qué el fallo no se detectó antes. En un contenedor limpio, `pip install .` fallaría con "package directory 'articulador_core' does not exist".

Además, `per-file-ignores` de ruff sigue apuntando a `articulador_core/logging_config.py`, que ya no existe en esa ruta — de ahí el nuevo `RUF001`.

**Por qué importa**
- No hay producto: no arranca, no se puede diagnosticar, no se puede empaquetar.
- **0 tests** significa que todo el resto de este informe se apoya en lectura de código, no en ejecución.
- Es un cambio de arquitectura **invisible en git**: si se pierde el working tree, se pierde el criterio de por qué se movió.

**Recomendación**
Decidir y **terminar** el movimiento en un commit único y coherente (`refactor: mueve articulador_core dentro de articulador_ui`):
1. Elegir el paquete canónico. Recomendación: `articulador_core` como paquete de primer nivel, **fuera** de `articulador_ui` (es lógica de dominio, no de presentación). Revertir el move, o
2. Si se quiere anidar: renombrar a `articulador_ui/core/` y actualizar **todos** los imports a `from articulador_ui.core import ...`, `packages`/`py-modules` en `pyproject.toml`, `--cov` en CI y gate, `mypy` paths, `bandit -r` paths, `per-file-ignores`, `docs/*.md` y los 16 módulos de test.
3. Verificar con el gate completo, no con el árbol instalado.

---

### 🟠 ALTO

#### A-1. `ArticuladorApp` es un God Object: 114 métodos y 2.110 líneas en un archivo

**Descripción**
`articulador_ui/app.py` concentra 11 responsabilidades distintas en una sola clase que hereda de `tk.Tk`: construcción de ventana, tematización, edición/zoom, ciclo de vida de documento, gestión del artículo de contexto (con diálogo embebido), ciclo de petición LLM, diálogo de revisión, persistencia de estado UI, menú de recientes, portapapeles y helpers de foco.

**Evidencia**
- `articulador_ui/app.py` — 2.110 líneas; `grep -c "^    def "` = **114**.
- `__init__` (85 líneas), `_theme` (121), `manage_references` (86, **construye un `Toplevel` completo inline** entre 1762–1847), `confirm_and_send` (70).
- Mixins/managers ya extraídos (`DocumentManager`, `LLMSessionManager`, `ChunkBuffer`, `DocumentScope`) demuestran que el patrón existe y funciona; `app.py` es la excepción.

**Por qué importa**
- Cualquier cambio toca el archivo más conflictivo del repo; el riesgo de regresión es alto y los tests deben cubrir la clase entera para probar una función.
- Es la causa raíz de A-2, M-1 y M-2: el estado de petición y de tema viven dispersos porque no tienen dueño.

**Recomendación**
Extraer, en este orden (por bajo riesgo), siguiendo el patrón ya establecido:
1. `ThemeController` (todo `_theme*`, `_reaplicar_*`, `_aplicar_*`).
2. `ChatController` (ciclo `request`/`finish`/`stream_chunk`/cancel + diálogo de revisión).
3. `ContextArticlesController` (y mover el diálogo de `manage_references` a `dialogs.py`).
4. Dejar en `ArticuladorApp` solo el ensamblado y `mainloop`.

Objetivo medible: `app.py` < 800 líneas y ningún método > 50.

---

#### A-2. Sin guarda de reentrada en `request()`: doble envío y respuestas perdidas

**Descripción**
`send_message()` y `review()` comprueban `session.request_active`, pero `request()` —el punto por el que pasa toda petición— **no comprueba nada** y establece el flag de forma incondicional. Además, la cancelación y el abort pueden limpiar peticiones distintas a la suya.

**Evidencia**
```python
# articulador_ui/app.py:1256-1266
def request(self, message: str, request_type: str = "normal"):
    ...
    if not self.profile.enabled or not self.key: self.append(...); return
    ...
    self.session.request_active=True; self.cancel_event=threading.Event(); ...
```
```python
# app.py:1957-1976  _cancel_active_request
self.llm.cancel(self.generation_counter)
self.request_types.clear()   # borra TODAS, no solo la cancelada
self.chunks.clear()          # idem
```

**Por qué importa**
- Si dos caminos entran (p. ej. `review()` mientras un envío está en `PREPARANDO`, o un atajo mal cableado), hay dos workers vivos y dos `request_id` en `request_types`.
- Un `Escape` en el momento equivocado vacía `request_types`; el `finish` posterior sale por `if request_id not in self.request_types: return` y **la respuesta se pierde en silencio**, sin mensaje al usuario.
- `request_active` se resetea en dos sitios con semánticas distintas (`_abort_request` vs `_cancel_active_request`), lo que hace el estado no determinista.

**Recomendación**
Introducir un `RequestState` real (id, `cancel_event`, fase, `streaming_text`) en lugar del flag suelto y del comentario fantasma (ver M-6):
- `request()` empieza con `if self.current_request is not None: return`.
- Cancelar opera **solo** sobre `self.current_request`.
- `finish(id)` valida identidad, no pertenencia a un dict.
- Test de regresión: cancelar durante `PREPARANDO` y enviar de inmediato no debe perder ninguna respuesta.

---

#### A-3. El guardado de credenciales no es transaccional y puede dejar config cambiada tras mostrar "Error al guardar"

**Descripción**
En el diálogo de configuración se persiste primero el TOML de perfiles y se muta `app.profiles`/`app.active_profile`; **después** se intenta guardar la key en el keyring. Si el keyring falla, el `except` muestra "Error al guardar" aunque la configuración **sí** cambió.

**Evidencia**
```python
# articulador_ui/dialogs.py:439-462
try:
    storage.save_profiles(working, active, app.config_path)   # commit 1
    app.profiles = working                                    # commit 2
    app.active_profile = active
    app.profile_chip.config(text=...)
    _persistir_credencial(app, active, key.get().strip(), remember.get())  # puede lanzar
    messagebox.showinfo("Configuración", "Perfil guardado.", parent=dialog)
    dialog.destroy()
except (OSError, RuntimeError) as error:
    ...   # muestra error, pero lo anterior ya está aplicado
```
`storage.delete_key()` puede propagar errores no-`PasswordDeleteError` (backend bloqueado), blanco del `except` anterior.

**Por qué importa**
Estado incoherente entre lo que el usuario cree y lo que está en disco; con credenciales esto es peor que un fallo limpio. Un reintento puede duplicar o dejar huérfana una key de sesión ya aplicada.

**Recomendación**
Invertir el orden y hacer rollback: aplicar keyring primero (devolver `(ok, err)` en vez de lanzar), luego `save_profiles`, y mutar `app.*` en último lugar. Ante cualquier fallo, restaurar el snapshot previo y no mostrar "guardado".

---

#### A-4. Lectura de keyring en el hilo de Tk: congelación de UI en las rutas críticas

**Descripción**
La propiedad `key` llama a `storage.load_key()` (→ `keyring.get_password`, que puede tardar 5–30 s con Secret Service bloqueado) **en cada evaluación**. Se evalúa varias veces por envío. Igual ocurre al cambiar de perfil en el diálogo.

**Evidencia**
```python
# articulador_ui/app.py:163-165
@property
def key(self) -> str:
    return os.environ.get(...) or self.session_keys.get(...) or storage.load_key(self.active_profile)
```
Evaluaciones por envío: `app.py:1179`, `1263`, `1379` (tres lecturas de keyring por mensaje), además de `dialogs.py:344` y `382` al cambiar de perfil.

**Por qué importa**
Contradice el diseño (correcto) del resto de la app, que mueve la red a workers y drena por cola. El síntoma es "la app se congela al enviar" y es intermitente según el estado del llavero — de los bugs más difíciles de reportar.

**Recomendación**
Resolver la key una sola vez (al elegir perfil / guardar credencial) y cachear en `self._resolved_key`; `key` pasa a ser atributo. En el diálogo, cargar las keys al abrir o fuera del hilo.

---

#### A-5. CI no tiene ninguna prueba de que el paquete se puede instalar y arrancar desde cero

**Descripción**
El pipeline instala con `pip install -e . --no-deps` y luego ejecuta los tests desde la raíz (donde `conftest.py` añade la raíz a `sys.path`). Ambos mecanismos **enmascaran** exactamente el tipo de fallo de C-1: errores de empaquetado (`packages`, `py-modules`, entry point) y paquetes que no se resuelven como instalados.

**Evidencia**
```yaml
# .github/workflows/ci.yml
- name: Install project
  run: |
    pip install -e . --no-deps
```
```python
# conftest.py
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
```
No existe paso de `pip install .` (no editable), ni de `pip check`, ni de instalar y ejecutar desde un directorio distinto del repo.

**Por qué importa**
El pipeline verde no garantiza que el paquete publicado se pueda instalar ni que `articulador` resuelva sus módulos. El release (`build-release.yml`) sí usa `-e`, con lo que el binario PyInstaller también se construye en el path enmascarado.

**Recomendación**
Añadir un job `package` que: (1) `python -m build`, (2) instale el wheel en un venv limpio fuera del repo, (3) ejecute `articulador --health` y `python -c "import ..."` desde `/tmp`, (4) `pip check`. Añadir también `--strict-markers` y `filterwarnings=error` para no acumular avisos.

---

### 🟡 MEDIO

#### M-1. `copy_response()` y `COLORS` son código muerto; comentarios que describen una arquitectura inexistente

**Evidencia**
- `grep -rn "copy_response"` → solo la definición (`app.py:943`). La misma función existe duplicada como `_copiar_mensaje` (`app.py:995`).
- `grep -rn "COLORS"` → solo `app.py:258` (escritura) y `tests/test_ui_integration.py:22` (un test que lo *inyecta*). Ningún diálogo lo lee.
- `models.py:74`: `# request_active ... se sincroniza con RequestState` y `llm_session_manager.py:18` igual — **`RequestState` no existe** (grep confirma).
- `docs/ARCHITECTURE.md` documenta a `ArticuladorApp` como dueño de `RequestState`.

**Por qué importa** Un lector (o un LLM asistente) perseguirá símbolos que no existen; los tests que fijan shims muertos consolidan la deuda.

**Recomendación** Borrar ambos, actualizar el test para asertar `es.SUPERFICIE` directamente, y corregir los tres comentarios y la fila de `ARCHITECTURE.md`.

#### M-2. `<Escape>` global cancelando peticiones desde diálogos modales

**Evidencia**
```python
# app.py:757
("<Escape>", self.cancel_request),
...
self.bind_all(secuencia, self._manejador_atajo(accion))
```
`bind_all` aplica a todas las ventanas hijas: pulsar Escape para cerrar el diálogo de configuración o el de revisión **también** cancela (y descarta) la petición en curso.

**Por qué importa** Pérdida de datos de trabajo por una pulsación razonable de teclado; muy difícil de diagnosticar para el usuario.

**Recomendación** `cancel_request` debe ignorar el evento si `winfo_toplevel()` del foco no es la ventana principal, o bindear Escape solo en el root.

#### M-3. `threat_feed` es un prototipo sin integración que sigue en `bandit`/mypy y contradice la promesa de la documentación

**Evidencia**
- 474 LOC + 310 LOC de tests; **cero llamadores** en `articulador_ui`/`articulador.py`.
- `CHANGELOG.md` y `docs/ARCHITECTURE.md` lo declaran "no integrado", coherente.
- `threat_feed.py:179` usa `urllib.request.urlopen` **sin** el opener sin redirects que sí protege `llm.py:146`, aunque el comentario dice que está validado.

**Por qué importa** Código de red sin dueño se degrada; el comentario de seguridad es correcto para el *primer* salto y falso para redirects.

**Recomendación** Mover a `experiments/` (excluido del paquete y de bandit) o integrarlo con `_NoRedirectHandler` y presupuesto de tiempo. En ambos casos, alinear el comentario.

#### M-4. Permisiones de directorios y ficheros de estado no fijadas explícitamente

**Evidencia**
```python
# storage.py:109
path.parent.mkdir(parents=True, exist_ok=True)          # umask del proceso (típico 0755)
# storage.py:114-124
mode = stat.S_IMODE(path.stat().st_mode) if exists else None
os.chmod(temporary, mode)                               # si no existía: hereda 0600 de mkstemp
```
`estado.json` contiene **todo el historial de conversaciones**; `~/.local/state/articulador/` puede quedar en 0755.

**Por qué importa** En máquinas multiusuario, la conversación no es privada. Contradice `docs/DATA_AND_PRIVACY.md`.

**Recomendación** `mkdir(..., mode=0o700)` y `mode=0o600` explícito para `config.toml`, `estado.json` y autosave.

#### M-5. `load_key()` convierte "llavero roto" en "no hay key"

**Evidencia**
```python
# storage.py:242-245
try:
    return keyring.get_password("articulador", profile) or ""
except Exception:
    return ""
```
**Por qué importa** Un backend bloqueado se reporta como "Configura un perfil LLM y una key", enviando al usuario a una pista falsa. `save_key`/`delete_key` ya distinguen.

**Recomendación** Capturar solo errores "sin entrada"; para el resto devolver un centinela/estado y mostrar aviso de backend en la barra de estado.

#### M-6. Autosave sin tope de tamaño y `parse_findings` parsea antes de limitar

**Evidencia**
- `autosave.py:42-45`: `return _autosave_path(document_path).read_text(...)` sin `stat()` previo (a diferencia de `document_manager` y `load_project`, que sí limitan).
- `review.py:15,50`: `json.JSONDecoder().raw_decode(clean[start:])` materializa el árbol completo antes de aplicar `MAX_FINDINGS`.

**Recomendación** Rechazar autosave > `MAX_ARTICLE_BYTES`; limitar `len(clean)` a ~512 KB antes de `raw_decode`.

#### M-7. Sin soporte High-DPI ni `tk scaling`

**Evidencia** `grep -rn "tk scaling|DpiAwareness|scaling" articulador_ui` → **0 resultados**. `estilo.py:163` fija `FAMILIA = "Inter"` sin lista de fallback.

**Por qué importa** En pantallas al 150–200 % la ventana queda borrosa y el tamaño de fuente es incorrecto; es un fallo de accesibilidad relevante para usuarios con baja visión.

**Recomendación** `ctypes.windll.shcore.SetProcessDpiAwareness(1)` (Windows) y escalar a partir de `tk scaling`; `fuente()` debe probar `tkinter.font.families()` y caer a `Segoe UI`/`DejaVu Sans`.

#### M-8. Diálogos con tamaños absolutos en píxeles

**Evidencia** `dialogs.py:135-136` (`760x520`, minsize `620x380`), `dialogs.py:282-283` (`700x620`, minsize `560x400`), `app.py:1768-1769`.

**Recomendación** Reutilizar el clamp de `_restaurar_geometria` (`min(pref, 0.9*screen)`) y bajar `minsize`.

#### M-9. `requirements-test.txt` duplicado e inconsistente con `pyproject.toml`

**Evidencia** `requirements-test.txt` (5 líneas, versiones abiertas `>=`, incluye `locust`) convive con el extra `dev` y con `requirements-dev.lock` (854 hashes). `locust` no está en ningún extra ni se ejecuta en CI.

**Recomendación** Eliminar `requirements-test.txt`; generar el lock con `--extra dev --extra perf` si `locust` se mantiene.

#### M-10. El "Informe visible" de errores no da ruta al log

**Evidencia** `app.py:1104-1113`: `logger.error(...)` con detalle, pero `messagebox.showerror` muestra un texto genérico sin ubicación del registro (`~/.local/state/articulador/articulador.log`).

**Recomendación** Botón "Ver detalles" con la ruta del log, o mostrarla en la barra de estado.

---

### 🔵 BAJO

| ID | Hallazgo | Evidencia |
|---|---|---|
| B-1 | `_worker_threads` se añade y nunca se poda; `chunks` no se limpia en `destroy()` | `app.py:123,1252,1394,2103-2110` |
| B-2 | `manage_references` construye su `Toplevel` inline en vez de usar `_abrir_dialogo`; divergen foco/Escape/grab | `app.py:1762-1847` |
| B-3 | Diálogo de configuración: `<Return>` no guarda; el campo de key queda tras los límites numéricos en el orden de Tab | `dialogs.py:472` |
| B-4 | `ToolTip` posiciona siempre debajo del widget; puede quedar fuera de pantalla; sin relación accesible | `tooltip.py:52-73` |
| B-5 | Estado `CANCELADO` promete "se descartará la respuesta tardía" pero el parcial ya se borró; el mensaje induce a error | `estado.py:78-82`, `app.py:1975` |
| B-6 | `estilo.colores()`/`app.COLORS` existen solo para un test | `estilo.py:145-159`, `tests/test_ui_integration.py:22` |
| B-7 | Formato denso con múltiples sentencias por línea (`;`) en `app.py`; `E701/E702` desactivadas explícitamente | `pyproject.toml` `ignore`, `app.py:694,889-900,1018` |
| B-8 | `estimate_prompt_tokens` es heurística carácter/3.2 sin overhead por mensaje; subestima en CJK | `llm.py:79-87` |
| B-9 | `_read_bounded`/`parse_findings` correctos, pero no hay filtro de redacción de secretos en logging | `logging_config.py:26-38` |

**Verificado como correcto (sin acción):**
- `atomic_write`: `mkstemp` → `fsync` → `chmod` → `os.replace` → `_fsync_directory`. Correcto.
- API keys nunca se serializan en TOML/JSON; solo keyring o variable de entorno (`storage.py:231-235`).
- `validate_endpoint` limita `http://` a loopback; `_NoRedirectHandler` impide robar cabeceras de autenticación (`llm.py:108-146`).
- Respuestas acotadas (`_read_bounded`, `MAX_SSE_LINE_BYTES`); path traversal bloqueado (`_validate_relative_path`).
- Workers no tocan Tk; cola drenada por `after(50, …)` con re-armado en `finally`.
- Logs rotativos sin contenido de artículos ni prompts; dependencias con lock hash-pinned y `pip-audit` en CI; Actions fijadas por SHA.

---

## 4. Roadmap ejecutable (Paso 4)

### Fase 0 — Desbloquear (1–2 h) · todo lo demás depende de esto

**Tarea: F0.1 Restaurar un árbol que importe**
- Severidad: 🔴 CRÍTICO · Esfuerzo: S · Dependencias: ninguna
- Problema: paquete reubicado a medias, 143 imports rotos, 0 tests.
- Solución: decidir ubicación canónica; alinear imports, `pyproject.toml` (`packages`), CI, gate, mypy, bandit, `per-file-ignores`, docs y los 16 tests. Commit atómico con `git mv` para preservar historia (`git log --follow`).
- Archivos: `articulador.py`, `articulador_ui/*.py`, `tests/*.py`, `pyproject.toml`, `.github/workflows/ci.yml`, `scripts/quality-gate.sh`, `docs/*.md`
- Verificación: `./scripts/quality-gate.sh` en verde con `pytest` contando >300 tests y 0 omitidos; `python articulador.py --health` desde un directorio ajeno al repo.

**Tarea: F0.2 Cerrar el agujero que permitió F0.1**
- Severidad: 🟠 ALTO · Esfuerzo: S · Dependencias: F0.1
- Solución: job `package` en CI con `python -m build` + instalación del wheel en venv limpio fuera del repo + `articulador --health` + `pip check`.
- Verificación: romper `packages` a propósito en una rama y comprobar que el job falla.

### Fase 1 — Integridad del estado de petición (1 día)

**Tarea: F1.1 `RequestState` real y guarda única de reentrada**
- Severidad: 🟠 ALTO · Esfuerzo: M · Dependencias: F0.1
- Solución: objeto único `current_request`; guarda en `request()`; cancelar operando solo sobre él; `finish(id)` valida identidad. Borrar comentarios de `models.py:74` y `llm_session_manager.py:18`.
- Archivos: `app.py`, `models.py`, `llm_session_manager.py`
- Verificación: tests de doble envío, cancelar-en-PREPARANDO, y respuesta tardía tras cancelar (la nueva respuesta de un segundo envío **no** se pierde).

**Tarea: F1.2 Escape sin efecto en diálogos modales**
- Severidad: 🟡 MEDIO · Esfuerzo: XS · Dependencias: F0.1
- Verificación: test con diálogo abierto + petición viva → Escape cierra el diálogo y **no** cancela.

**Tarea: F1.3 Credenciales transaccionales + keyring fuera del hilo**
- Severidad: 🟠 ALTO · Esfuerzo: M · Dependencias: F1.1
- Solución: keyring primero con `(ok, err)`, rollback de `profiles`, cache de `_resolved_key`.
- Verificación: test que simula `keyring` levantando → no queda config alterada y la key no se lee en el hilo principal.

### Fase 2 — Arquitectura (3–5 días)

**Tarea: F2.1 Extraer `ThemeController`**
- Severidad: 🟠 ALTO · Esfuerzo: M · Dependencias: F1.*
- Verificación: `app.py` baja ~400 líneas; tests de tema (`test_tema.py`) pasan sin cambios de aserción.

**Tarea: F2.2 Extraer `ChatController`**
- Severidad: 🟠 ALTO · Esfuerzo: L · Dependencias: F2.1, F1.1
- Verificación: `app.py` < 1.200 líneas; mediante cobertura, `ChatController` ≥ 80 %.

**Tarea: F2.3 Extraer `ContextArticlesController` y mover su diálogo a `dialogs.py`**
- Severidad: 🟡 MEDIO · Esfuerzo: M · Dependencias: F2.2
- Verificación: `app.py` < 800 líneas, ningún método > 50 líneas.

### Fase 3 — Privacidad, accesibilidad y limpieza (2 días)

| Tarea | Sev. | Esfuerzo | Verificación |
|---|---|---|---|
| F3.1 Permisos `0700`/`0600` en estado y credenciales/config | 🟡 | XS | Test que asertá `stat().st_mode` tras escribir `estado.json` |
| F3.2 `load_key` distingue backend roto; aviso en barra | 🟡 | S | Test con keyring que lanza `RuntimeError` |
| F3.3 Tope en autosave y en `parse_findings` | 🟡 | XS | Test con autosave de 10 MB |
| F3.4 High-DPI + fallback de fuente | 🟡 | S | Manual en Win 200 %/Linux 150 % |
| F3.5 Clamp de tamaños de diálogo | 🟡 | XS | Test con `winfo_screenheight` simulado |
| F3.6 Borrar código muerto (`copy_response`, `COLORS`) y corregir comentarios/docs | 🟡 | XS | `ruff --select F` + grep vacío |
| F3.7 Decidir `threat_feed`: `experiments/` o integrado con no-redirect | 🟡 | S | No está en `bandit`/cobertura si se archiva |
| F3.8 Unificar dependencias de test; borrar `requirements-test.txt` | 🟡 | XS | `pip install -e ".[dev]"` + lock |
| F3.9 Error visible con ruta al log | 🟡 | XS | Manual |

### Fase 4 — Pulido (opcional)

B-1 poda de hilos, B-2 unificar diálogo, B-3 Tab/Enter en configuración, B-4 tooltip en pantalla, B-5 redacción de estado, B-8 estimación de tokens, B-9 filtro de redacción de logs.

---

## 5. Matriz de dependencias

```
F0.1 ──┬─► F0.2
       ├─► F1.1 ──┬─► F1.2
       │          └─► F1.3 ──┐
       └─► F2.1 ──► F2.2 ──► F2.3
                    F1.1 ───┘
F1.* ──► F3.1..F3.9 (paralelizables entre sí)
F2.3 ──► F3.6 (limpieza de muertos tras mover)
```

Ruta crítica: **F0.1 → F1.1 → F1.3 → F2.2 → F2.3**. Fase 3 puede ejecutarse en paralelo por otra persona desde F0.2.

---

## 6. Deuda técnica (orden de impacto)

| Deuda | Impacto | Esfuerzo de pago |
|---|---|---|
| `app.py` (God Object, 2.110 L) | Alto — frena toda evolución | L |
| Estado de petición disperso (`request_active`/`request_types`) | Alto — bugs silenciosos | M |
| Ambientes enmascarados (`-e`, `conftest`, árbol instalado) | Alto — CI verde sin garantías | S |
| Código muerto + comentarios mentirosos + docs desalineadas | Medio — entropía de conocimiento | XS |
| Prototipo `threat_feed` sin dueño | Medio | S |
| Dependencias duplicadas (`requirements-test.txt`) | Bajo | XS |
| Formato denso (`;`) en `app.py` | Bajo | S |

---

## 7. Quick wins (< 30 min cada uno)

1. **F0.1** — es *el* quick win: devuelve la vida a 300+ tests.
2. Borrar `copy_response()` y `app.COLORS` + ajustar un test (M-1, B-6).
3. `mkdir(..., mode=0o700)` y `mode=0o600` en `atomic_write` (M-4).
4. `stat()` con tope en `read_autosave` (M-6).
5. Guardar identidad de toplevel en `cancel_request` (M-2).
6. Borrar `requirements-test.txt` y documentar `pip install -e ".[dev]"` (M-9).
7. Corregir los 3 comentarios sobre `RequestState` y la fila de `ARCHITECTURE.md`.

---

## 8. Métricas

| Métrica | Valor actual | Objetivo |
|---|---|---|
| Tests ejecutados | **0** (1 error de colección) | >300, 0 omitidos |
| Cobertura (`--cov-fail-under=70`) | no medible | ≥70 %, ≥80 % en `core` |
| Verdes de `ruff` / `mypy` | **2 errores** / no ejecuta | 0 / 0 |
| `app.py` | 2.110 L, 114 métodos | < 800 L, ningún método > 50 |
| Imports rotos | **143** | 0 |
| Líneas de producto / tests | ~5.100 / ~4.900 (ratio ≈ 0,96) | mantener ≥0,8 |
| CI: jobs de empaquetado | 0 | 1 |
| DPI-awareness | ausente | presente |

---

## 9. Primera tarea a ejecutar

> **F0.1 — Restaurar un árbol que importe.**
> Decidir la ubicación canónica de `articulador_core` (recomendado: revertir el move y dejarlo como paquete de primer nivel), actualizar los 143 imports, `pyproject.toml`, CI, gate, mypy, bandit, docs y tests, y **commitear con `git mv`**. Criterio de cierre: `./scripts/quality-gate.sh` en verde con >300 tests y 0 omitidos, y `python articulador.py --health` funcionando desde un directorio ajeno al repo.

---

*Auditoría realizada solo lectura; no se modificó ningún archivo del repositorio. Los hallazgos de `articulador_ui/` y `articulador_ui/articulador_core/` fueron obtenidos por exploración dedicada y **verificados por muestreo directo** en los puntos de mayor impacto (C-1, A-2, A-4, M-1, M-2, M-7) antes de reportarlos.*
