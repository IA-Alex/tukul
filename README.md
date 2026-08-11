# Articulador

Editor conversacional local para escribir y revisar artículos Markdown con un LLM remoto opcional. La conversación es el espacio principal; el artículo permanece editable a la derecha.

## Ejecutar

```bash
python3 articulador.py
```

También puedes abrir un documento:

```bash
python3 articulador.py /ruta/articulo.md
```

## Flujo

1. Escribe o abre un artículo.
2. Conversa con Articulador en lenguaje natural; selecciona texto si quieres enfocar la consulta.
3. Usa **Revisar artículo** para una revisión de ortografía, gramática, semántica, redundancias y estructura.
4. Guarda el Markdown o un proyecto recuperable que conserva artículo, contexto elegido y conversación.

El contexto local se indexa desde el *workspace* elegido, excluyendo aplicación, plugins y carpetas ocultas. El índice conserva en caché los archivos sin cambios, reindexa solo los modificados y limita el uso de memoria a 500 archivos de hasta 50 KB cada uno. Antes de enviarlo, Articulador muestra los archivos que usará y permite excluirlos.

## LLM y key

Abre **Propiedades → Modelo** para configurar el proveedor, endpoint, modelo y límites. Incluye plantillas para DeepInfra, DeepSeek, OpenRouter, Ollama, Anthropic, Gemini y cualquier API compatible con OpenAI. El selector no impide usar un endpoint personalizado.

La key puede mantenerse solo durante la sesión o recordarse en el llavero del sistema mediante `keyring`; nunca se escribe en el TOML ni en un JSON local. Una variable de entorno con el nombre configurado tiene prioridad. Para recordar la key instala dependencias:

```bash
pip install -r requirements.txt
```

Los diagnósticos técnicos se guardan en `~/.local/state/articulador/articulador.log`; no incluyen el artículo, la conversación ni API keys.

## Calidad

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile articulador.py articulador_core/*.py articulador_ui/*.py
```
