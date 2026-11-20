# Guía de usuario

Tukul es un taller de escritura: puedes partir de una idea, reunir referencias,
desarrollar un borrador y revisarlo. El texto se edita en tu equipo; el modelo
te ayuda mediante una conversación y tú decides qué conservar.

La guía rápida también está disponible dentro de Tukul, en el menú **Guía de
usuario…**.

## Primera vez

1. Abre Tukul y elige **Configurar modelo…** en el menú.
2. Selecciona un proveedor, indica el endpoint y el nombre del modelo. Para un
   proveedor remoto, configura también su API key. Para un modelo local
   compatible con OpenAI, usa el endpoint local correspondiente.
3. Guarda el perfil. Buscar en la web y leer artículos locales no necesitan
   una clave del proveedor; conversar sí requiere una credencial no vacía. Si
   tu servidor local no valida claves, consulta si acepta una credencial de
   relleno: Tukul la incluye en la petición.

Puedes consultar [Configuración](CONFIGURATION.md) para ver todos los campos y
opciones. Tukul no incluye una cuenta de modelo ni una API key.

## Empezar desde una idea

Escribe en el chat algo como:

> Tengo esta idea: [idea]. Ayúdame a definir el enfoque, la audiencia y un esquema.

Después puedes pedir cambios concretos: comparar dos enfoques, aclarar la tesis,
reordenar secciones, desarrollar un punto o ajustar el tono. Si ya tienes un
borrador, ábrelo con **Abrir artículo…** o `Ctrl+O`, o pégalo en el editor de la
izquierda. Selecciona un fragmento para concentrar la conversación en esa parte.

## Buscar referencias

**Buscar en Internet…** permite buscar un tema o una pregunta. Tukul muestra
títulos, enlaces y fragmentos encontrados por GDELT. Selecciona los resultados
que quieras añadir al contexto y abre sus enlaces para leer y verificar las
fuentes originales. La búsqueda no descarga las páginas completas ni confirma
por sí sola que una referencia sea correcta.

Para usar artículos propios, abre **Contexto de artículos…**:

- **Añadir artículos…** incorpora archivos `.md` o `.txt` que elijas.
- **Buscar en memoria…** encuentra documentos en la carpeta local configurada.
- **Añadir artículo activo** agrega el documento que tienes abierto.
- **Consultar MCP…** conecta a un servidor MCP local, permite elegir una consulta
  marcada como de solo lectura y muestra la respuesta para revisarla antes de
  añadirla al contexto.

El soporte MCP es opcional. Instálalo con `pip install 'tukul[mcp]'` (o
`pip install -e '.[mcp]'` en una copia de desarrollo). En **Consultar MCP…**
indica el ejecutable y sus argumentos como una lista JSON, por ejemplo
`["servidor", "--opcion", "valor"]`. Tukul lanza el proceso local sin shell;
confirma que confías en el ejecutable antes de continuar. La configuración no
se guarda salvo que marques **Recordar ejecutable y argumentos**. No incluyas
claves o secretos en esos argumentos. El servidor se ejecuta con los permisos
de tu usuario y puede acceder a Internet según su configuración.

Tukul solo muestra herramientas cuyo servidor declare `readOnlyHint: true`, y
confirma cada consulta. Esa marca es una declaración del servidor, no una
garantía de que sea inocuo. La respuesta MCP se considera material no confiable;
solo entra al contexto si la revisas y aceptas. Cada consulta inicia y cierra el
servidor local. Esta primera versión no admite servidores MCP remotos ni OAuth.

Por defecto, la memoria local apunta a `Articulos/` junto al programa; en una
instalación distribuida esa carpeta puede no existir. Puedes elegir la carpeta
de tus artículos y reindexarla en **Configurar modelo… → Carpeta de artículos**.
La memoria indexa archivos Markdown y texto; no importa PDF ni otros formatos
binarios. Solo los documentos que selecciones se añaden al contexto.

## Conversar, revisar y guardar

Al añadir referencias, eliges explícitamente cuáles autorizar para el proveedor
configurado. El artículo activo también puede formar parte de cada consulta; si
el contexto no está autorizado, Tukul pide confirmación antes de enviarlo.
El proveedor remoto procesa el contenido que se le envía según sus propias
condiciones. Consulta [Datos y privacidad](DATA_AND_PRIVACY.md) antes de enviar
material sensible.

Usa **Revisar artículo** para obtener hallazgos sobre ortografía, gramática,
semántica, redundancias y estructura. Revisa las sugerencias antes de aplicarlas.
Guarda el documento como Markdown o guarda un proyecto si quieres conservar
juntos el artículo y la conversación.

## Qué requiere Internet

- Buscar en Internet y añadir CVE recientes requiere conexión a las fuentes
  públicas correspondientes y solo se ejecuta cuando eliges esas acciones.
- Conversar con un modelo remoto requiere conexión al endpoint del proveedor.
- Consultar MCP requiere el paquete opcional instalado y el ejecutable del
  servidor configurado; el propio MCP no añade fuentes de noticias.
- Buscar en la carpeta local no requiere conexión.

La conexión de búsqueda web consulta GDELT. **Añadir CVE recientes** es una
herramienta distinta, enfocada en vulnerabilidades de software; no es una fuente
general de noticias.
