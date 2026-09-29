# Datos y privacidad

## Clasificación y ubicación

| Clase | Datos | Ubicación / formato | Lifecycle |
|---|---|---|---|
| `LOCAL_DATA` | Markdown, proyectos, `estado.json`, config | rutas elegidas por el usuario; texto/JSON/TOML | permanece hasta edición o eliminación del usuario |
| `REMOTE_DATA` | prompt: system prompt, artículo, contexto aprobado, conversación; respuesta | request/response del proveedor configurado | transitorio en Tukul; retención del proveedor es externa |
| `SECRETS` | API key | variable de entorno, memoria de sesión o keyring del sistema | hasta que se quite de la env/sesión/keyring |
| `TRANSIENT_DATA` | chunks, buffers, respuestas en memoria, temporales atómicos | proceso y temporales del mismo directorio | termina al completar/cancelar/cerrar; temporales se reemplazan o limpian |

La app almacena localmente el artículo, hasta 30 turnos por documento en `estado.json`, recientes y geometría/zoom. Un proyecto guarda ruta relativa y hasta 30 mensajes. El autosave es un Markdown por documento bajo `~/.local/state/tukul/autosave/`; se escribe mientras hay cambios sin guardar y se borra después de guardar o cerrar explícitamente.

Los logs están en `~/.local/state/tukul/tukul.log` (512 KB + 2 backups). Registran diagnóstico estructurado, no contenido del artículo, conversación ni API keys. El estado UI tiene un límite de 2 MiB; la respuesta LLM y los cuerpos HTTP tienen límites internos documentados en `tukul_core/llm.py`.

## Eliminación y recuperación

El usuario elimina artículos, proyectos, config, estado, logs y autosaves desde el filesystem; Tukul no implementa retención remota ni borrado remoto. Para recuperar, conserva el Markdown original y copia el autosave antes de reemplazarlo. La escritura atómica evita archivos parcialmente escritos, pero no sustituye un backup. Recomienda respaldar artículos y proyectos fuera del directorio de estado.

No se afirma cumplimiento regulatorio ni una política de retención del proveedor. Antes de enviar material sensible, revisa el endpoint, la cuenta y la política del proveedor.
