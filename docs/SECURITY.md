# Seguridad

Este documento describe controles presentes, no una certificación formal. La aplicación es local, pero puede enviar contenido y credenciales a un proveedor seleccionado por el usuario.

## Supuestos y límites

- El usuario controla su máquina, archivos y endpoints configurados.
- HTTPS protege el transporte hacia endpoints remotos; no se verifica aquí la honestidad del proveedor ni el contenido que devuelve.
- HTTP está permitido solo para loopback, principalmente Ollama.
- Artículos, contexto, conversaciones y respuestas son datos no confiables: el prompt instruye al modelo a no obedecer instrucciones contenidas en esos datos.
- No existe aislamiento fuerte del proceso contra un usuario local con acceso al filesystem o al keyring.

## Controles

| THREAT | ASSET | ATTACK_SURFACE | CURRENT_CONTROL | RESIDUAL_RISK | TEST_EVIDENCE |
|---|---|---|---|---|---|
| Endpoint remoto HTTP roba key | API key | URL en TOML | HTTPS obligatorio; HTTP solo loopback | CA/TLS y proveedor comprometidos siguen fuera del control | `tests/test_auditoria_regresion.py` (`TestSeguridadDelEndpoint`) |
| Redirect exfiltra headers | API key | respuesta 3xx | opener sin redirects | un proxy o proveedor ya comprometido puede observar la request original | `TestNoRedireccionDeCredenciales` |
| TOML/JSON expone secrets | API key | persistencia local | keys solo env/keyring/sesión | env y keyring son responsabilidad del host | `TestCredenciales` |
| Prompt injection en artículo/contexto | instrucciones del sistema | contenido enviado al LLM | system prompt trata datos como no confiables y exige aprobación de contexto | el proveedor/modelo puede ignorar instrucciones | tests de prompting/contexto |
| Respuesta remota agota memoria | disponibilidad | SSE/body | límites de línea, body y respuesta acumulada | límites son aproximaciones y el proveedor puede cortar antes | `TestLecturaSSEAcotada`, `TestRespuestaCompletaAcotada` |
| Proyecto malicioso escapa su carpeta | archivos locales | ruta relativa JSON | validación POSIX/Windows y resolución bajo base | symlinks y permisos del host requieren revisión operativa | tests de rutas |
| Estado/autosave corrupto | disponibilidad/datos | JSON y backups | carga defensiva, escritura atómica, recuperación | corrupción simultánea o fallo de disco | tests de storage/UI |
| Dependencia vulnerable | proceso | paquetes Python/actions | lock con hashes, `pip-audit`, Bandit high/high en CI | findings no bloqueantes pueden requerir revisión | workflow CI |

## Secretos y logging

La prioridad de la key es variable de entorno del perfil, luego key de sesión y luego keyring. `config.toml`, `estado.json`, proyectos y logs no deben contener API keys. El log JSON rota a 512 KB con dos backups; registra metadatos técnicos, no artículos, conversaciones ni respuestas completas. Evita incluir secretos en mensajes de error y URLs.

## Ingesta y proveedor

Enviar artículo, selección, contexto aprobado y conversación al proveedor es una acción explícita de la consulta. El proveedor puede conservar o procesar esos datos según su propia política, que Articulador no controla. Un proveedor malicioso puede devolver instrucciones, datos falsos o respuestas excesivas; la app no los convierte en comandos ni modifica archivos automáticamente.

## Actualizaciones y reporte

Las dependencias de desarrollo se fijan en `requirements-dev.lock`; CI ejecuta `pip-audit`. Las GitHub Actions del workflow están fijadas por SHA. No hay un proceso externo de disclosure configurado en el repositorio; reporta vulnerabilidades al mantenedor del repositorio antes de divulgarlas públicamente.
