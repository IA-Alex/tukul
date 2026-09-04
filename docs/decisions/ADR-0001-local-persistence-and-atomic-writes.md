# ADR-0001: persistencia local y escritura atómica

STATUS: Accepted

## CONTEXT

Articulador maneja artículos y estado local sin servidor propio. Un corte durante una escritura no debe dejar un archivo parcial.

## DECISION

Usar archivos TOML/JSON/Markdown locales y `storage.atomic_write`, que escribe un temporal en el mismo directorio, hace flush/fsync, conserva permisos cuando corresponde y reemplaza con `os.replace`.

## ALTERNATIVES

Escritura directa; base de datos local; servicio remoto.

## CONSEQUENCES

El sistema es portable y operable sin servicio adicional, pero el backup y la retención quedan a cargo del usuario. El autosave complementa, no sustituye, un backup.

## SECURITY_IMPACT

Las API keys no se guardan en estos archivos; los temporales se crean con permisos restrictivos antes del reemplazo.

## TESTING_IMPACT

Tests de escritura atómica, permisos, proyectos y estado UI validan el contrato.
