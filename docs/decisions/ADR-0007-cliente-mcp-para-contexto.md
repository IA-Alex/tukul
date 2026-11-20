# ADR-0007: cliente MCP local para enriquecer contexto de artículos

STATUS: Accepted

## Contexto

Tukul permite desarrollar artículos con referencias locales y búsquedas web,
pero usuarios pueden tener fuentes accesibles mediante servidores MCP. La
aplicación mantiene el control sobre qué material llega al proveedor LLM y ya
ofrece una aprobación explícita para el contexto.

## Decisión

- Añadir un cliente MCP opcional basado en el SDK oficial de Python, por el
  transporte local `stdio`.
- Mantener el MCP separado de `LLMClient`: MCP conecta la aplicación con
  servidores de contexto/herramientas y no cambia el protocolo del proveedor
  LLM.
- Mostrar solo herramientas cuyo servidor anuncia `readOnlyHint: true`.
- Solicitar confirmación al iniciar el ejecutable local y antes de cada llamada.
- Mostrar la respuesta como contenido no confiable y pedir una aprobación
  separada antes de añadirla al contexto.
- Ejecutar llamadas fuera del hilo de Tk, con timeout y límite de salida.
- Persistir ejecutable y argumentos solo cuando el usuario marca la casilla;
  no se admiten claves como argumentos de configuración.

## Consecuencias y límites

- `mcp` es una dependencia opcional; Tukul conserva su instalación base ligera.
- El servidor se inicia y cierra en cada operación. Esto evita mantener
  procesos remotos vivos, aunque puede añadir latencia al listar y llamar.
- `readOnlyHint` es metadato autodeclarado, no un permiso impuesto por Tukul.
  El proceso hereda los permisos del usuario y no se ejecuta en sandbox.
- La primera versión no conecta por HTTP, OAuth o recursos MCP, no entrega
  credenciales al servidor y no permite que el modelo invoque herramientas.
- Se puede extender más adelante con transporte remoto autenticado y lectura
  de recursos tras evaluar su modelo de autorización.

## Alternativas

- **Hacer que el modelo elija y ejecute herramientas MCP:** pospuesto; exige
  un ciclo de tool-calling específico del proveedor y controles de aprobación
  adicionales. La versión inicial conserva la mediación de la aplicación.
- **Implementar MCP dentro de `LLMClient`:** rechazado porque mezcla el
  transporte de contexto con el protocolo de proveedor.
- **Permitir HTTP/OAuth en el MVP:** pospuesto por gestión de credenciales,
  autenticación y seguridad de endpoints remotos.
