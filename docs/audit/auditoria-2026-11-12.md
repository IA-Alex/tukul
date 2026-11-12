# Auditoría desktop + diseño — Tukul (2026-11-12)

Skills: `auditor-frontend-desktop-elite` (intensidad Completa) + `frontend-design-pro`.
Modalidad autorizada: auditoría **y aplicación de correcciones**.
Método: lectura estática + herramientas autorizadas (ruff, mypy, pytest con cobertura).
No se ejecutó la GUI interactivamente más allá de sondas de Tk bajo Xvfb.

## 1. Dictamen

**APTO CON RESERVAS.**

El núcleo es sólido: 677 pruebas pasan (88 % de cobertura), `mypy` limpio, `ruff`
limpio en el código del proyecto, transporte HTTP sin redirecciones con validación
de esquema, escrituras atómicas con `fsync` y permisos 0600, secretos fuera del
TOML. La arquitectura y la seguridad no presentan hallazgos abiertos de peso.

Las reservas son de **interfaz**: tres defectos confirmados de zoom, theming de
scrollbars y usabilidad del diálogo de revisión, más un problema de señalización
solo-emoji en el generador de ideas. Ninguno es crítico; todos son reparables de
forma acotada y con verificación.

## 2. Cobertura

- **Stack:** Python ≥ 3.11, Tkinter + ttk (tema `clam`). Objetivo Linux X11 y
  Windows x86_64 (standalone PyInstaller). macOS no soportado.
- **Alcance revisado:** `tukul_core/` (34 módulos), `tukul_ui/` (app, componentes,
  diálogos, tema, tooltip, ideas), `tukul.py`, workflows de CI y build-release,
  `pyproject.toml`.
- **Exclusiones:** `Articulos/` (contenido del usuario, no del producto),
  `.venv`, `build/`, `dist/`, caches. `evals/` y `tests/performance/` revisados
  solo de pasada.
- **Herramientas ejecutadas:** `ruff check .` (2 avisos I001, ambos en
  `Articulos/plugins/.../build_evidence_packet.py`, fuera del producto);
  `mypy tukul_core` (limpio); `pytest` con cobertura (677 passed, 88 %);
  sondas Tk bajo `xvfb-run` para confirmar comportamiento de scrollbars, zoom y
  valores por defecto de `ScrolledText`.
- **No evaluado:** firma/notarización de artefactos reales (no hay binario
  disponible en el entorno; H0 — bloqueo de minutos de Actions — sigue abierto e
  impide producir el Release verificable); accesibilidad con lector de pantalla
  real (AT-SPI); comportamiento en Windows real (no disponible aquí);
  `pip-audit` contra advisory vivo (sin red/credenciales en este entorno).

## 3. Hallazgos

| ID | Sev. | Conf. | Estado | Ubicación | Impacto | Corrección |
|----|------|-------|--------|-----------|---------|------------|
| DF-001 | Alta | Alta | CONFIRMADO | `tukul_ui/app.py:1034` (`_aplicar_escala`) | El zoom (Ctrl+±) no repinta la línea de estado, la barra de aprobación ni los menús: quedan a la escala antigua mientras el resto crece. Función central incoherente. | Repintar fuentes de todos los portadores con fuente explícita al cambiar zoom. |
| DF-002 | Media | Alta | CONFIRMADO | `tukul_ui/components/editor_panel.py:25`, `tukul_ui/app.py:623` (`_text`) | `ScrolledText` usa `tkinter.Scrollbar` clásico (`#d9d9d9`, canal `#b3b3b3`) y un `Frame` `#d9d9d9`; los estilos `Vertical.TScrollbar`/`Horizontal.TScrollbar` de `tema.py` nunca se aplican. Editor, campo de mensaje e historial muestran scrollbar y canto claros en tema oscuro. | Estilizar `.vbar` y `.frame` del `ScrolledText` y reaplicar al cambiar de tema. |
| DF-003 | Media | Alta | CONFIRMADO | `tukul_ui/dialogs.py:182` | El `Listbox` de hallazgos del diálogo de revisión no tiene scrollbar. Con un artículo largo (decenas de hallazgos) las filas fuera de vista solo se alcanzan con teclado; el ratón no permite navegarlas y no hay indicio de que haya más. | Añadir `ttk.Scrollbar` enlazado al `Listbox`. |
| DF-004 | Media | Alta | CONFIRMADO | `tukul_ui/ideas.py:307-323` | La lista de ideas comunica urgencia y audiencia solo con emoji (🔴🟠🟡🟢 / 👔💻👥👤). Es señal por color exclusivamente (contradice el principio del propio proyecto en `estado.py`: el color no informa en solitario) y los emoji pueden salir como caja vacía si no hay fuente de emoji de color. | Añadir la etiqueta textual de urgencia y audiencia junto al emoji. |
| DF-005 | Baja | Media | CONFIRMADO | `tukul_ui/components/editor_panel.py:20-23`, `assistant_panel.py:20-25` | Rótulos y subtítulos que narran la función de la sección («Tu espacio de escritura», «Tu compañero de escritura», «Escribe, pega o abre un artículo para comenzar.») no aportan nada a un usuario que vuelve y compiten con el contenido. | Recortar a la etiqueta del panel; mover orientación al mensaje de bienvenida (ya existe). |
| DF-006 | Baja | Media | CONFIRMADO | `tukul_ui/components/top_bar.py:188-194` | El nombre del documento se recorta por **caracteres** (`nombre[:41]`) mientras el chip de modelo se recorta por **píxeles** (`_texto_modelo`). En fuentes anchas o con zoom el recorte por caracteres desborda o sobra. | Medir por píxeles como el chip de modelo. |

### Refutación

- **DF-001:** se descartó que `_theme()` (llamado por `_aplicar_escala`) resolviera
  las fuentes: los `ttk.Label` con `style=` sí se reconfiguran, pero
  `estado_label` y `aprobacion_label` fijan `font=` explícita y los `tk.Menu`
  viven fuera de `ttk.Style`. Sonda: `estado_label` 11→11 y menú 12→12 tras
  `es.ZOOM=1.4` + `_aplicar_escala()`, frente a editor 14→20. Confirmado.
- **DF-002:** se comprobó que no hay ningún `option_add("*Scrollbar*")` ni
  configuración de `.vbar`/`.frame`; `ScrolledText.__init__` usa
  `Scrollbar(self.frame)` (clásico). Sonda: `vbar background=#d9d9d9`.
  Confirmado.
- **DF-003:** se buscó toda aparición de `Scrollbar` en `tukul_ui`: solo
  `dialogs.py:471` (canvas de configuración) e `ideas.py:284`. Ninguna ligada al
  `Listbox` de revisión. Confirmado.
- **DF-004:** la vista previa sí escribe «Urgencia: …» (ideas.py:355), pero la
  fila de la lista no; el dato solo está en el emoji. Confirmado.
- **Contra la hipótesis «rol del historial por color»:** refutada — `append`
  escribe el nombre textual («Tú» / «Tukul») en el historial; el color es
  redundante, no el único portador.
- **Contra la hipótesis «placeholder se envía como mensaje»:** refutada —
  `_enviar_desde_input` corta si `_placeholder_activo`.

## 4. Correcciones aplicadas

Ver `CHANGELOG.md` (0.4.1) y las pruebas nuevas en
`tests/test_zoom_coherente.py`, `tests/test_scroll_clasico_tematico.py` y
`tests/test_ideas_etiquetas.py`.

- **DF-001:** `_aplicar_escala` ahora repinta `estado_label`, la barra de
  aprobación y los menús (barra, recientes, contextual, historial).
- **DF-002:** helper `estilizar_area_texto` en `tema.py`; se aplica al construir
  y al cambiar de tema.
- **DF-003:** scrollbar `ttk` en el diálogo de revisión, con reaplicación de tema.
- **DF-004:** etiqueta textual de urgencia y audiencia en cada fila de ideas.
- **DF-005:** se retiran los subtítulos de narración; queda la etiqueta del panel
  y la orientación del mensaje de bienvenida.
- **DF-006:** el nombre del documento se recorta por píxeles.

## 5. Verificaciones pendientes que cambiarían el dictamen

- run real de `build-release.yml` que produzca binarios + `SHA256SUMS` (sigue
  bloqueado por el problema de cuenta de H0, no de código).
- Prueba en Windows real del recorte de scrollbar clásico (opciones de estilo de
  `Scrollbar` difieren algo entre X11 y Windows).
- Accesibilidad con AT-SPI real sobre el editor y el historial.
