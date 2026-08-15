# Articulador

Editor conversacional local para escribir y revisar artículos Markdown con un LLM remoto opcional. La conversación es el espacio principal; el artículo permanece editable a la izquierda.

## Ejecutar

```bash
python3 articulador.py
```

O, tras una instalación del paquete (`pip install -e .`), con el comando:

```bash
articulador
```

También puedes abrir un documento:

```bash
python3 articulador.py /ruta/articulo.md
```

## Flujo

1. Escribe o abre un artículo.
2. Conversa con Articulador en lenguaje natural; selecciona texto si quieres enfocar la consulta.
3. Usa **Revisar artículo** para una revisión de ortografía, gramática, semántica, redundancias y estructura.
4. Guarda el Markdown o un proyecto recuperable que conserva artículo y conversación.

El contexto local es explícito: puedes añadir artículos previos desde **Contexto de artículos…**. Se conservan al abrir otro artículo y, antes de enviarlos junto al artículo activo, Articulador pide confirmación de privacidad.

## LLM y key

Abre **Configurar modelo…** (en el menú) para configurar el proveedor, endpoint, modelo y límites. Incluye plantillas para DeepInfra, DeepSeek, OpenRouter, Ollama, Anthropic, Gemini y cualquier API compatible con OpenAI. El selector no impide usar un endpoint personalizado.

La key puede mantenerse solo durante la sesión o recordarse en el llavero del sistema mediante `keyring`; nunca se escribe en el TOML ni en un JSON local. Una variable de entorno con el nombre configurado tiene prioridad. Para recordar la key:

```bash
pip install ".[keyring]"
```

## Diagnósticos y respaldo

Los diagnósticos técnicos se guardan en `~/.local/state/articulador/articulador.log`; no incluyen el artículo, la conversación ni API keys.

Los cambios sin guardar se respaldan automáticamente en `~/.local/state/articulador/autosave/` y se ofrecen para restaurar si la aplicación se cierra de forma inesperada.

## Calidad

Hay una sola puerta de calidad, espejo del pipeline de CI:

```bash
pip install -e ".[dev]"
./scripts/quality-gate.sh   # ruff + mypy + pytest con cobertura (mínimo 70 %)
```
