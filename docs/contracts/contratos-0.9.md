# Contrato de cierre — Tukul 0.9.0

Estado: **abierto**.
Sucede al candidato local 0.8.4, que no se publicó: su acta quedó pendiente
de credencial válida para los evals y de tag. Las capacidades nuevas de MCP y
la guía de usuario abren un contrato nuevo conforme a
[POLITICA_CONGELACION.md](../POLITICA_CONGELACION.md).

## Propósito y alcance

Tukul sigue siendo un taller local de escritura Markdown con apoyo opcional de
LLM. Este contrato incorpora dos capacidades de producto:

### F7 — Orientación y guía de usuario

- La bienvenida explica el flujo de desarrollar ideas y convertirlas en
  artículos, con acciones existentes para referencias, borrador y revisión.
- La guía de usuario se puede abrir desde el menú y documenta instalación,
  configuración, fuentes, persistencia y límites.
- Aceptación: regresiones de UI de bienvenida y acceso a la guía pasan; los
  pasos documentados corresponden a la aplicación.

### F8 — Consultas a servidores MCP locales

- Conexión opcional por stdio, habilitada con el extra mcp.
- Solo aparecen herramientas que anuncian readOnlyHint: true; Tukul vuelve a
  comprobar la marca antes de cada invocación.
- Se confirma el inicio del ejecutable y cada llamada; la salida se muestra y
  requiere aprobación independiente antes de entrar al contexto del LLM.
- La operación se ejecuta fuera del hilo de Tk y tiene timeout de 30 segundos,
  máximo de 30.000 caracteres, sin shell y sin heredar variables sensibles.
- Guardar el comando es optativo; no se guardan credenciales ni se ofrece
  ejecución autónoma por el modelo.
- Aceptación: pruebas del cliente y del flujo UI cubren herramientas permitidas
  y rechazadas, respuesta/error, límites, cancelación/cierre y aprobación del
  contexto. Debe existir al menos una prueba local con un servidor MCP real por
  stdio; los mocks no prueban el contrato de integración.

## Capacidades heredadas

El contrato conserva F5–F6 del contrato 0.8: prompts separados por modo y
defensa común contra contenido no confiable. Sus tres evals de prompt siguen
siendo requisito de aceptación; una credencial inválida o un run ausente se
registra como No verificado, nunca como aprobado.

## Criterios transversales de cierre

1. ./scripts/quality-gate.sh pasa con cero omitidas y cobertura mínima de 70 %.
2. CI pasa en Python 3.11, 3.12 y 3.13; el extra MCP está instalado en el job y
   la prueba real por stdio se ejecuta sin omisiones.
3. Los tres evals promptfooconfig*.yaml alcanzan el criterio definido en cada
   configuración con credencial válida; conservar sus reportes.
4. pyproject.toml, uv.lock, --health y CHANGELOG declaran 0.9.0;
   uv lock --check pasa.
5. El ejecutable Linux se construye, ejecuta --health y cumple el suelo de
   glibc; verificar checksum y firma desde el artefacto descargado.
6. El tag anotado v0.9.0 identifica exactamente el código validado. No se
   publica ni etiqueta mientras haya criterios sin aprobar.

## Riesgos y límites declarados

MCP ejecuta un proceso con los permisos locales del usuario. readOnlyHint es
una declaración del servidor, no aislamiento ni un permiso impuesto. El usuario
debe confiar en el ejecutable configurado. El proveedor LLM puede retener el
contenido enviado según sus propias condiciones. C3 (lector de pantalla) y
cuotas/continuidad del proveedor siguen fuera de este contrato mientras no
afecten una capacidad esencial comprometida.

## Reglas de corte

- Solo defectos confirmados de capacidades existentes admiten parches sobre una
  versión congelada; funciones nuevas requieren un contrato nuevo.
- No se reescriben tags ni releases publicados.
- Una verificación pendiente no se presenta como verde. La falta de credencial,
  entorno o artefacto mantiene abierto el criterio correspondiente.
- No se crea tag ni Release hasta completar todas las condiciones anteriores.
