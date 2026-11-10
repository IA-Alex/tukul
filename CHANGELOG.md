# Historial de cambios

Todas las modificaciones relevantes del proyecto. El formato sigue las
recomendaciones de [Keep a Changelog](https://keepachangelog.com/es-ES/) y el
proyecto se versiona según [Semantic Versioning](https://semver.org/lang/es/).

## [0.4.0] - 2026-11-10

Esta versión cierra la auditoría arquitectónica del 2026-11-10: retira código
muerto, documenta el subsistema de fuentes en tiempo real y sube la cobertura
de los adaptadores de red.

### Cambiado

- **Barra superior reagrupada en tres zonas**: acciones sobre el archivo
  (menú, Guardar), documento activo con su estado, y configuración tras un
  separador fino (contexto, modelo, tema, panel). Desaparece la fila plana en
  la que todo pesaba lo mismo y el nombre del artículo quedaba emparedado.
- El **nombre del artículo se ve siempre**: sin documento dice «Sin artículo
  abierto» en lugar de dejar un hueco vacío, y cuando falta sitio cede primero
  el estado («Sin cambios») y luego se recorta el nombre, nunca al revés.
- El **tamaño mínimo de la ventana sube a 1120×540**: por debajo, la barra no
  cabe y el nombre del artículo desaparecía. En pantallas más estrechas el
  suelo se recorta a la pantalla para no dejar la ventana cortada.
- Textos de la barra sin relleno: `☀ Claro` / `☾ Oscuro`, `Contexto: 0` y
  `Panel IA (F6)` con texto fijo. Lo que hace cada control vive en su tooltip,
  y así el ancho de los botones no cambia con cada estado.
- **Paleta rehecha** a partir del *tunkul* maya, del que toma el nombre el
  proyecto (Diccionario de americanismos, ASALE): madera quemada y médula de
  caña en las capas, fibra de bambú en los bordes y un verde de lengüeta como
  único acento, en lugar del ocre y el azul de la narrativa anterior. Cambian
  los colores; el comportamiento y los tokens son los mismos. Contrastes
  verificados (AA en texto, 3:1 en bordes) por `tests/test_accesibilidad.py`.
- Nuevos tokens `borde_control` (bordes de controles, sash y scrollbar, ≥ 3:1
  según WCAG 1.4.11) y `superficie_activa` (hover de botones). `borde` queda
  como divisoria sutil, también ≥ 3:1 contra las tres capas.

### Añadido

- `tukul_ui/request_lifecycle.py`: el ciclo de una petición (arrancar el worker,
  resolver la key dentro del hilo, publicar `complete`/`error`, cancelar) en un
  solo sitio. `TukulApp` lo usa para el envío normal y la revisión en lugar de
  repetir el bloque; cobertura del módulo 100 %.
- `tukul_ui/tema.py`: el sistema ttk completo (estilos, mapas de estado y
  opciones derivadas del tema) en una función `aplicar_estilos`. `TukulApp._theme`
  pasa de ~145 líneas a una delegación. Cobertura 97 %.
- `tukul_ui/ventana.py`: el saneado puro del estado de ventana (geometría, zoom
  y recientes). `TukulApp` delega en él conservando su API; cobertura 100 %.
- `tukul_ui/ideas.py`: el pipeline completo de ideas (consulta de fuentes,
  correlación, generación, diálogo de selección y su reaplicación de tema),
  extraído de `TukulApp` a un controlador que recibe la ventana por inyección
  (`IdeasHost`). `TukulApp` conserva una fachada con la API histórica.
- `tukul_ui/contexto.py`: `ContextArticle` en un módulo neutral, para que los
  controladores lo importen sin ciclos con `app.py` (que lo re-exporta).
- `tukul_ui/contexto_dialogo.py`: el diálogo «Contexto de artículos» y la
  fuente de amenazas (consulta NVD/EPSS/KEV en hilo daemon, upsert y
  autorización del contexto, reaplicación de tema), extraídos de `TukulApp` a
  un controlador con la ventana inyectada (`ContextHost`). `TukulApp` conserva
  la fachada y sigue siendo el dueño de `context_articles`.
- `scripts/paleta_preview.py` genera la hoja de muestras de los dos temas
  (`docs/screenshots/paleta-tukul.png`), que el README enlaza. Un test falla si
  la paleta cambia sin regenerarla.
- Tests de contrato HTTP del cliente LLM contra un servidor local
  (`tests/test_llm_http_contract.py`): SSE real, `Retry-After`, 302 que no se
  sigue, techo de cuerpo y cabecera de credencial por protocolo.
- `tukul_ui/worker_threads.py`: registro de los hilos de trabajo, que se espera
  en el cierre y se vacía en el hijo de un `fork()`.
- Paridad verificada entre `scripts/quality-gate.sh` y CI
  (`tests/test_quality_gate_parity.py`).

### Eliminado

- Las clases históricas del pipeline Fogg (`FoggEngine`, `ConflictDetector`,
  `SuggestionGenerator`, `PostValidator`): la interfaz nunca las consumió y solo
  las sostenía su propio test. `impact_analyzer.py` queda con `CorrelationEngine`
  e `IdeaGenerator`, que son los que usa el diálogo de contexto. Los modelos
  (`FoggAnalysis`, `SourceConflict`, `ConsumerSuggestion`) siguen en `models.py`.
- `tukul_ui/ui_state_manager.py`: módulo huérfano sin importadores; el estado de
  interfaz ya vive en `storage.load/save_ui_state` y `tukul_ui/ui_state.py`.

### Corregido

- El botón de menú de la barra medía 149 px para un solo icono: en el tema
  `clam`, un `Menubutton` se estira hasta el ancho de su desplegable y se comía
  el hueco del nombre del artículo. Ahora tiene ancho fijo y el menú completo
  sigue disponible al desplegarlo.
- El chip del modelo crecía con el nombre del perfil y podía empujar la barra
  por encima del ancho de la ventana. Se recorta por píxeles (no por
  caracteres) y el nombre completo aparece en el tooltip.
- `--health` y el log explican un campo de perfil ignorado por tipo, con perfil,
  campo y valor recibido. Antes el perfil arrancaba con los valores por defecto
  y nada lo indicaba. `4096.0` se acepta como `4096`; un booleano no se acepta
  como número.
- El gate local ejecuta `--health`, el contrato CLI, `pip-audit` y
  `bandit -lll -ii`, y avisa con el comando de instalación si falta el paquete.
- Un worker que tocaba `after()` con la ventana ya destruida podía abortar el
  proceso (`RuntimeError: main thread is not in main loop`): fuera del hilo de
  Tk ahora solo se registra.
- El diálogo de ideas pedía la misma confirmación dos veces.
- `_read_bounded` drena el cuerpo rechazado en vez de cortar el socket a medias.
- `SECURITY.md` ya no presenta la fuente CVE como un prototipo no integrado.
- Cancelar durante el reintento ya no espera al final del backoff: el envío
  termina en cuanto se marca la cancelación.
- Una respuesta que pide herramientas (`tool_calls`) se reconoce y se ignora con
  aviso en el log, en vez de llegar como texto vacío sin explicación.
- El worker de ideas ya no escribe en el log: formatear una excepción desde ese
  hilo durante la recolección de basura podía abortar el proceso entero.
- Reabrir el documento activo (por ejemplo desde «Recientes») durante una
  consulta borraba la respuesta: la conversación guardada se sustituía por la
  de una sesión recién creada, así que el texto se veía en pantalla pero no
  quedaba en el historial ni en `estado.json`, sin ningún aviso.
- Cancelar una consulta afectaba a un evento compartido del manager en vez de al
  de la petición cancelada; ahora cada petición cancela exactamente la suya y
  `LLMSessionManager.cancel` solo cierra su stream HTTP.
- El aviso «espera o cancélala» al enviar con una consulta en curso prometía un
  botón que queda retirado fuera de una petición.
- Test de cierre del llavero: se sustituye el temporizador que competía con la
  latencia del runner por una sincronización determinista, origen de fallos
  intermitentes en la suite completa.
- Hallazgos de la auditoría de 2026-11-02 que seguían abiertos:
  - **Privacidad del estado.** `estado.json` (que guarda todo el historial de
    conversaciones), el autosave y `config.toml` se crean con permisos `0600`
    y su carpeta con `0700`; antes heredaban el umask (0755 típico) y eran
    legibles por otros usuarios de la máquina.
  - **Llavero caído ≠ «no hay key».** `storage.load_key` distingue «no existe
    la entrada» de un backend sin respuesta y lanza
    `KeyringUnavailableError` en el segundo caso. La interfaz lo avisa en el pie
    («El llavero no responde…») en vez de pedir configurar una key que sí existe.
  - **Topes de lectura.** `read_autosave` rechaza respaldos de más de 5 MB y
    `parse_findings` descarta la respuesta antes de `raw_decode` si supera
    512 KB, sin materializar el árbol JSON.
  - **El error visible dice dónde está el registro.** El diálogo de error incluye
    la ruta del log, o avisa de que no hay archivo en esa instalación.
  - **High-DPI y fuente con reserva.** La app se declara DPI-aware en Windows,
    calibra `tk scaling` con el DPI real y elige la primera familia instalada
    (`Inter` → `Segoe UI` → `DejaVu Sans`…) en vez de caer en una fuente ajena.
  - **Los diálogos caben en la pantalla.** Tamaño preferido recortado con margen
    de 32/64 px: en un portátil de 1366x768 el de configuración dejaba sus
    botones fuera de alcance.
  - **Código muerto retirado.** `app.COLORS`, `estilo.colores()` y los
    comentarios sobre un `RequestState` inexistente; `docs/ARCHITECTURE.md`
    describe el dueño real del estado de petición.
  - **Una sola fuente de dependencias de test.** Se retira
    `requirements-test.txt` y `locust` pasa al extra `dev`.
- La geometría guardada de la ventana vuelve a restaurarse cuando está a la
  izquierda o por encima del origen del escritorio: Tk la escribe como
  `1920x1011+-61+-23` y el patrón anterior no casaba con `+-61`, así que se
  abría con el tamaño por defecto. La normalización vive en
  `TukulApp._geometria_saneada`, la usan tanto la restauración como el guardado
  y acota tamaño y posición al escritorio actual.
- Una ventana aún no mapeada ya no persiste su `geometry()` provisional
  (`1x1+0+0`), que encogía la próxima apertura al mínimo.
- Auditoría conductual de la interfaz:
  - «Cancelar» deja de aparecer como botón gris en reposo: sigue visible para
    descubrir la salida, pero sin relieve (estilo `Inactivo`) hasta que hay una
    consulta viva. Antes un control sin función competía con «Revisar artículo».
  - Enviar y Revisar vuelven a habilitarse al cerrar una petición. `finish`
    dejaba Enviar apagado tras el primer éxito y `_reset_request_ui` no liberaba
    Revisar. «Guardar» ya no depende del estado de la consulta.
  - El pie de estado conserva el último mensaje útil: seleccionar texto ya no
    lo sobrescribía mientras había una consulta activa o un error sin resolver.
  - La barra y el título muestran el artículo activo (con `•` si hay cambios
    sin guardar). Antes solo decían «Tukul».
  - El foco inicial llega al editor: «Guardar» sale del recorrido por Tab, que
    ahora empieza por «Menú».
  - El tema `clam` de ttk se fija en el arranque, antes de crear estilos.
  - El enunciado de bienvenida no se duplica ni pisa una conversación
    restaurada al reabrir la aplicación.
  - Los tooltips de la barra no se salen por el borde derecho de la pantalla.
  - La línea de uso de tokens se oculta hasta que el modelo informa de consumo
    real, en vez de repetir el texto de ayuda.
  - Metadatos de 11 px (antes 10) y texto del asistente ajustado al ancho real
    del panel (antes un `wraplength` fijo de 300 px).
  - «Revisar artículo» explica en un tooltip qué revisa y que no modifica el texto.
- Instalación e importación: el paquete `articulador_core` vuelve a la raíz y
  la copia anidada en `articulador_ui/` se elimina. `pip install` y el arranque
  volvían a fallar con `ModuleNotFoundError` y un árbol de trabajo no válido.
- `show_review_dialog` superaba la complejidad permitida (C901): el resumen de
  cada hallazgo y la comprobación de ámbito se extraen a funciones propias, así
  que `ruff` vuelve a pasar sin excepciones nuevas.
- Atajos globales (`Ctrl+S`, `Ctrl+O`, `Escape`, `F6` y el zoom) ya no actúan
  desde dentro de un diálogo: antes guardaban o abrían archivos por debajo del
  modal con el foco.
- Los menús contextuales (clic derecho en editor e historial) se destruyen al
  cerrarse. Antes se acumulaba un `tk.Menu` por clic durante toda la sesión.
- El modo foco (F11) conserva un botón de menú: ocultaba la barra completa y
  dejaba sin acceso a «Configurar modelo», «Recientes» y «Abrir proyecto».
- Los tooltips de la ventana principal no aparecen encima de un diálogo modal.
- La API key del llavero ya no se lee en el hilo de Tk: la lectura ocurre en un
  hilo daemon, el resultado se cachea y el envío la resuelve dentro de su worker
  con un tope de espera. Antes podía congelar la interfaz al enviar o al abrir
  «Configurar modelo».
- Se retira `copy_response()`, que no tenía ninguna llamada.
- `docs/ARCHITECTURE.md` documenta el subsistema de fuentes en tiempo real
  (`real_time_feed` + `impact_analyzer`): sus componentes, la degradación
  granular por fuente, el transporte sin redirects y el diagrama del pipeline.
  Antes la doc normativa describía un sistema más pequeño que el real.
- `docs/TRACEABILITY.md` gana la fila de «sugerencias de impacto», la capacidad
  con superficie de red propia que estaba sin trazar.
- Cobertura de los adaptadores de red: `arxiv` pasa de 68 % a 99 % y `epss` de
  72 % a 86 %, con tests de las rutas de error (URLError/TimeoutError con
  reintento, `Retry-After` acotado, techo de bytes y parseo tolerante de fecha
  y score).
- `WorkerThreads.vivos()` poda los hilos ya terminados del registro. Antes el
  set conservaba una referencia por cada worker que la sesión hubiera arrancado
  (memoria que solo crecía en uso prolongado) y, en la suite, un doble inyectado
  por una prueba quedaba «vivo» para las siguientes: una comprobación legítima
  de «no hay hilos al cerrar» fallaba según el orden de ejecución. Se añade
  `WorkerThreads.reset()` y una fixture autouse que aísla el registro entre
  pruebas. Regresión cubierta en `tests/test_worker_threads.py`.

### Añadido

### Añadido

- `scripts/verify-install.sh`: instala el paquete en un entorno aislado, lo
  importa desde fuera del checkout y arranca `articulador --health`. Se invoca
  desde `scripts/quality-gate.sh` y desde CI: antes, `pip install -e .` y el
  `conftest.py` ocultaban que la instalación real estaba rota.
- `tests/test_installation_integrity.py`: guardas de contrato (paquetes
  declarados existentes, no anidados y importables sin `conftest.py`).
- Pruebas de regresión para cada corrección de interfaz y credenciales:
  `test_atajos_dialogos.py`, `test_menus_contextuales.py`, `test_modo_foco.py`,
  `test_reentrada_peticiones.py`, `test_keyring_hilo.py` y dos casos nuevos en
  `test_tooltip.py`.

### Eliminado

- macOS de `build-release.yml`: no es un objetivo soportado. Se retira el
  binario `tonal-macos-arm64` también del Release `v0.3.2` ya
  publicado. Solo Linux y Windows.

### Seguridad y mantenimiento

- Se regeneró `requirements-dev.lock` con versiones actualizadas y hashes para
  eliminar vulnerabilidades conocidas detectadas por `pip-audit`.
- El prototipo aislado `ThreatFeed` queda documentado como no integrado y fuera
  del contrato funcional de esta versión.

## [0.3.2] - 2026-08-17

### Corregido

- `build-release.yml`: el job `release` no tenía `permissions: contents:
  write`, así que `softprops/action-gh-release` fallaba con 403 al intentar
  publicar el Release (confirmado en el run que disparó el tag `v0.3.1`: los
  tres binarios compilaron bien, pero el Release nunca se creó). Sin cambios
  de código de aplicación en esta versión.

## [0.3.1] - 2026-08-17

### Añadido

- `.github/workflows/build-release.yml`: ejecutables standalone (sin Python
  instalado) para Linux, Windows y macOS, compilados con PyInstaller en un
  runner nativo de cada sistema. Publica un GitHub Release con los tres
  binarios al empujar un tag `vX.Y.Z`.
- `LICENSE` (MIT) y metadata de empaquetado (`license`, `classifiers`,
  `[project.urls]`) en `pyproject.toml`: sin esto, publicar el paquete
  (PyPI o cualquier release) quedaba en ambigüedad legal.

### Corregido

- La consola de Windows arranca en `cp1252`, no UTF-8: el primer emoji o
  acento que `--health` imprimía (o que el logger de consola registraba)
  tronaba con `UnicodeEncodeError` y tumbaba la app antes de mostrar nada.
  No era un problema del empaquetado: pasaba igual corriendo
  `python tukul.py` nativo en Windows. `sys.stdout`/`sys.stderr` se
  reconfiguran a UTF-8 al arrancar `main()`.

## [0.3.0] - 2026-08-17

### Añadido

- Estado de interfaz persistente: geometría de ventana, nivel de zoom,
  documentos recientes y conversación se guardan en `estado.json` (junto a
  `config.toml`) y se recuperan al reabrir Tukul. Persistencia atómica,
  igual que el resto del proyecto; nunca falla la carga (JSON corrupto o
  ausente equivale a estado vacío).
- Conversación por documento: cada artículo conserva su propia hebra entre
  reinicios. Cambiar de artículo dentro de la misma sesión abre la
  conversación de ese documento (o una vacía si es nuevo) en vez de arrastrar
  los turnos del anterior.
- Modo foco (`F11`): oculta la barra superior y el pie para dejar solo el
  artículo visible; se restaura sin perder la disposición de paneles.
- Zoom del cuerpo tipográfico (`Ctrl` `+`/`-`/`0`), acotado entre 80 % y 150 %.
- Documentos recientes: submenú en el menú Archivo, con tope de 10 entradas y
  opción de vaciar la lista.
- Tooltips (`tukul_ui/tooltip.py`) en los controles de la barra
  superior, sin dependencias externas.
- Copiar un mensaje individual del historial de conversación desde su menú
  contextual.
- Métrica de palabras seleccionadas junto al total, en el pie del editor.

### Corregido

- El diccionario de conversaciones persistidas se poda a los documentos
  vigentes (en recientes o el activo) en cada guardado de estado, evitando que
  `estado.json` crezca sin límite con cada artículo que se abrió alguna vez.
- Ajustes menores de contraste y jerarquía tipográfica en el sistema visual
  (`estilo.py`), verificados contra WCAG 1.4.11 en las tres capas de fondo.
- `destroy()` espera (con tope) a que terminen los hilos de `review()`/
  `request()` antes de destruir la ventana, evitando que uno arranque tarde
  y sobreviva al cierre.

## [0.2.1] - 2026-08-15

### Añadido

- Reintentos con backoff en `LLMClient` ante errores transitorios (408, 429,
  5xx) y fallos de conexión, respetando la cabecera `Retry-After`. Se reintenta
  solo la apertura de la conexión, nunca a mitad de un stream.
- Autosave y recuperación ante cierres abruptos: el artículo sin guardar se
  respalda en `~/.local/state/tukul/autosave/` y se ofrece restaurarlo al
  reabrir el documento.
- Tope de tamaño en la apertura de artículos (5 MB) para no agotar la RAM.
- Cobertura medida y exigida en el pipeline (mínimo 70 %).

### Eliminado

- El índice BM25 y el orquestador de contexto automático
  (`tukul_core/context.py`, `tukul_ui/context_orchestrator.py`),
  que quedaron sin uso al pasar a contexto explícito de artículos.
- La bandera `--workspace` de la CLI, sin efecto desde aquel cambio.
- `scripts/lint.sh`, absorbido por `scripts/quality-gate.sh`.

### Corregido

- `storage._atomic_write` pasa a ser `storage.atomic_write` (API pública usada
  por `DocumentManager`).
- Cancelación unificada en un único `_cancel_active_request`; antes había dos
  copias que ya divergían.
- La barra de aprobación de contexto se oculta al cancelar la petición.
- `DocumentManager.open_project` captura ahora `UnicodeError` en la lectura.

## [0.2.0] - 2026-08-12

- Interfaz visual "Articulator" (sistema de capas, estados explícitos).
- Diálogo de revisión estructurado; el prompt técnico y el JSON no llegan al
  historial ni a la conversación.
- `DocumentScope`: estado derivado del documento, reemplazado en bloque.
- Canal de chunks (`ChunkBuffer`) separado de la cola de control garantizada.
- Pipeline de CI (ruff, mypy, pytest bajo X, diagnóstico `--health`).
