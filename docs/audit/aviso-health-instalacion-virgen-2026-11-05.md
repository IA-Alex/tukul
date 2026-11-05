# Avisos de `--health` en una instalación virgen (2026-11-05)

## Lo que pasa hoy

En un equipo donde Tukul nunca se ha ejecutado, `tukul.py --health` devuelve:

```
Salud: ISSUES
  config: /home/<usuario>/.config/tukul/config.toml
  storage: ⚠️  La carpeta de config no existe (se creará al guardar)
  llm: ⚠️  Sin perfiles habilitados
  logging: ✓ OK (archivo: .../tukul.log)
```

## ¿Es intencionado?

Sí, y está fijado por contrato en tres sitios:

1. `tukul_core/health.py` separa explícitamente «con avisos» de «inservible»:
   `has_errors()` solo cuenta `ComponentStatus.ERROR`, con el comentario
   «una instalación recién estrenada (sin carpeta de config ni perfiles) ya
   cuenta como no sana». El código de salida de la CLI se decide con `has_errors`,
   y por eso un primer arranque sale con 0.
2. `tests/test_auditoria_regresion.py::test_instalacion_nueva_tiene_avisos_pero_no_errores`
   lo fija: `is_healthy == False` y `has_errors == False`.
3. Los dos mensajes describen hechos reales del sistema, no fallos: la carpeta
   se crea al guardar y sin un perfil configurado Tukul no puede conversar.

Conclusión: **no es un defecto**. El comportamiento actual es correcto y no
debería cambiarse sin una decisión explícita, porque el aviso es la única señal
que tiene un usuario nuevo de que falta configurar el LLM.

## El problema real

El problema no es que avise, sino **cómo lo hace**. La salida dice `ISSUES`
(el estado global) y los mensajes empiezan por el síntoma técnico («La carpeta
de config no existe») antes que por la acción («configura un perfil»). Para
quien instala por primera vez, eso se lee como «la instalación está rota»,
cuando lo que falta es un paso normal de configuración.

## Opciones

### Opción A — Mantener el aviso y mejorar la redacción (recomendada)

- `storage` y `llm` siguen en `WARNING`; el código de salida sigue siendo 0.
- Se redacta como primer arranque: «Aún no hay perfiles: completa
  `config.toml` para conversar» y «La carpeta de config se creará al guardar
  (todavía no existe)».
- Se añade al final de la salida una línea de siguiente paso cuando ambos
  avisos aparecen juntos: «Para empezar, copia `tukul.example.toml` a la ruta
  de config indicada arriba y pon tu API key».
- Coste: cambio de texto en `health.py` y ajuste de las pruebas que fijan las
  cadenas. No cambia el modelo de estados ni el código de salida.
- Riesgo: bajo. Ningún consumidor depende del texto exacto: las cadenas solo
  aparecen en `tukul_core/health.py` y en `scripts/paleta_preview.py`, que usa
  «Sin perfiles habilitados» únicamente como texto de muestra de una paleta
  (no como aserción). Las pruebas de salud comprueban estado y código de salida
  —no el texto—; solo este documento cita los literales.

### Opción B — Crear un perfil por defecto en el primer arranque

- Tukul sembraría un `config.toml` con un perfil de ejemplo al no encontrar
  ninguno; el aviso de `llm` desaparecería.
- Coste: cambio de comportamiento con escritura en disco del usuario sin que
  lo haya pedido, y un perfil «de ejemplo» que puede confundirse con uno real.
  Además, el perfil sembrado seguiría sin estar habilitado mientras no tenga
  endpoint, modelo y key, así que el aviso reaparecería disfrazado.
- Riesgo: medio. Modifica la experiencia de primer arranque y añade estado
  persistente que hay que mantener y migrar.

## Recomendación

**Opción A.** Mantiene el contrato verificado (exit 0, nada roto) y arregla lo
único que confunde: el texto. La Opción B resuelve el mensaje creando un
fichero que el usuario no pidió y que no elimina la necesidad de configuración.

## Estado

**Opción A aplicada** (2026-11-05), tras aprobación explícita:

- `storage`: «Aún no existe (se crea al guardar la configuración)».
- `llm`: «Ninguno configurado todavía (ver «siguiente paso»)».
- Nueva línea `siguiente paso: copia tukul.example.toml a <ruta>, pon tu API
  key y ejecuta --health otra vez`, que solo aparece cuando storage y llm
  están ambos en WARNING y ningún componente en ERROR.
- El estado global sigue en `ISSUES` y el código de salida sigue siendo 0: el
  contrato no cambió. Solo cambió cómo se lee.

Salida de una instalación virgen:

```
Salud: ISSUES (…)
  config: /home/<usuario>/.config/tukul/config.toml
  storage: ⚠️  Aún no existe (se crea al guardar la configuración)
  llm: ⚠️  Ninguno configurado todavía (ver «siguiente paso»)
  logging: ✓ OK (archivo: .../tukul.log)
  siguiente paso: copia tukul.example.toml a /home/<usuario>/.config/tukul/config.toml, pon tu API key y ejecuta --health otra vez
```

Por qué no se eligió la Opción B: sembrar un config por defecto escribe en el
disco del usuario sin pedirlo y el perfil sembrado seguiría deshabilitado (sin
endpoint, modelo ni key), así que el aviso reaparecería con otro disfraz.

La Opción A no modifica el modelo de estados ni el código de salida.
