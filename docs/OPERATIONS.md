# Operaciones y troubleshooting

## Runbook

**INSTALL:** con Python 3.11+ disponible: `pip install -e .`; para guardar keys en el llavero: `pip install -e '.[keyring]'`. Los ejecutables standalone se publican para Linux x86_64 y Windows x86_64 cuando el workflow de release se ejecuta.

**START:** `python3 tukul.py [ARTICULO.md]` o `tukul [ARTICULO.md]`. Diagnóstico: `python3 tukul.py --health`; código 1 significa error, no solo warning.

**LOCATIONS:** config `~/.config/tukul/config.toml`; estado `estado.json` junto al config; log `~/.local/state/tukul/tukul.log`; autosave `~/.local/state/tukul/autosave/`.

**HEALTH_CHECK:** ejecuta `--health`, comprueba storage, perfiles LLM y logging, y confirma la ruta realmente inspeccionada. Un perfil deshabilitado puede ser warning utilizable; carpeta de config inexistente se crea al guardar.

**BACKUP:** copia artículos y proyectos a un destino externo. No trates `estado.json` o autosave como backup único.

## Incidentes

| SYMPTOM | LIKELY_CAUSE | DIAGNOSTIC | SAFE_ACTION | DATA_LOSS_RISK |
|---|---|---|---|---|
| no arranca | Python/Tk ausente | `--health`; `python -c 'import tkinter'` | instala runtime/Tk; conserva archivos | bajo si no borras estado |
| config inválida | TOML o campo fuera de rango | `--health`; revisa log | corrige una copia siguiendo `CONFIGURATION.md` | bajo; loader usa defaults |
| estado ignorado | JSON corrupto o >2 MiB | log y presencia de `estado.json` | copia el archivo y renómbralo manualmente; la app regenerará estado | recientes/conversación persistida pueden perderse |
| artículo no abre | ruta ilegible o >5 MiB | permisos, tamaño, log | corrige permisos o abre una copia | no sobrescribas el original |
| keyring falla | backend ausente/bloqueado | `--health` y mensaje de settings | usa key de sesión/env; instala/configura keyring | la key no debe copiarse a TOML |
| provider falla | key, modelo, cuota, HTTP | log, código HTTP y endpoint | verifica endpoint/key/modelo; espera si 429 | artículo local no se borra |
| red falla | DNS/TLS/firewall/timeout | prueba `--health` y logs; no pegues keys en comandos | revisa conectividad y HTTPS | respuesta incompleta no reemplaza el artículo |
| límite de tokens | contexto o total excedido | mensaje de UI | reduce contexto/artículo o aumenta límites del perfil dentro del modelo | bajo |
| stream interrumpido | timeout, cancelación o proveedor | estado de UI y log | reintenta; conserva el texto recibido como respuesta parcial según UI | no se pierde el Markdown guardado |
| cancelación | usuario pulsa Esc | estado Cancelado | inicia una nueva consulta cuando termine el cierre | bajo |
| cierre | ventana cerrada durante request | esperar cierre normal; revisar autosave | deja terminar/cancelar; restaura autosave si aparece | cambios no guardados dependen de autosave |

**RESET:** cierra la app y respalda antes de mover `estado.json`, `config.toml` o `autosave/`. No borres esos archivos como primer diagnóstico. Para resetear solo la UI, mueve `estado.json` a un nombre de respaldo y arranca; para resetear perfiles, edita una copia o mueve `config.toml` conservando la original.
