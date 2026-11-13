# Auditoría conector-proveedor — Tukul (2026-11-13)

Verifica que las superficies del conector LLM (documentación, cliente de
producto y adaptador de evaluación) coincidan con lo que realmente promete el
proveedor DeepInfra. Método: lectura estática + contraste contra el contrato
público de DeepInfra, con ejecución real de solo lectura de las respuestas de
error.

Los identificadores de esta serie son **`C-01..C-03`**, deliberadamente
distintos de los `H-01..H-08` de
[`auditoria-conector-2026-11-12.md`](auditoria-conector-2026-11-12.md), que
cubren otro conjunto de hallazgos (fechas naive, MITRE, EPSS). La colisión de
rótulos impedía distinguir a qué serie pertenece cada hallazgo.

## 1. Alcance y contexto

- **Transporte revisado:** el de `tukul_core/llm.py` hacia el protocolo OpenAI
  Chat Completions (DeepInfra, Novita, compatible). El transporte ya estaba
  verificado en la serie anterior; aquí se revisan las **superficies** que lo
  rodean.
- **Flujos:** configuración del perfil `deepinfra`; propagación del error del
  proveedor a la UI; fidelidad del adaptador de evaluación.
- **Revisado en:** `82d9d65`.

## 2. Dictamen

**CORREGIDO.** Los tres hallazgos eran desajustes entre superficies, ninguno del
transporte. Severidad original: alto 1 · medio 1 · bajo 1. Quedan corregidos y
con regresión.

## 3. Hallazgos

### C-01 — [ALTO] La documentación del perfil `deepinfra` contradecía al ejemplo

- **Síntoma:** `docs/CONFIGURATION.md` documentaba el perfil `deepinfra` con
  `provider = "openai_compatible"`, contradiciendo a `tukul.example.toml` y a su
  propia tabla de proveedores.
- **Promesa incumplida:** el README y `tukul.example.toml` prometen que cada
  perfil declara su id real, con su hint y validación de endpoint base. Un
  usuario que copiara el bloque de la doc perdía esa identidad.
- **Clasificación:** defecto confirmado.
- **Corrección:** el id pasa a `provider = "deepinfra"`. Se añade
  `tests/test_validacion_perfil.py::TestDocumentacionUsaLosProveedoresReales`,
  que cruza el bloque TOML de la doc con `PROVIDERS` igual que ya hacía el test
  del ejemplo.
- **Prueba que falla antes y pasa después:** verificada en ambas direcciones.
  Con la doc anterior el test falla
  (`'provider = "deepinfra"' not found in … provider = "openai_compatible"`);
  con la corrección pasa.

### C-02 — [MEDIO] El adaptador de evaluación declaraba una fidelidad que no tenía

- **Síntoma:** el docstring de `evals/proveedor_tukul.py` afirmaba medir «lo que
  la app envía de verdad», pero el adaptador fuerza `temperature=0` + `seed=7`.
  El cliente de producto envía `profile.temperature` (0.5 por defecto) y no
  manda `seed`.
- **Promesa incumplida:** el propio docstring del adaptador; no hay promesa de
  producto.
- **Clasificación:** defecto confirmado de documentación (no de comportamiento).
- **Corrección:** se documenta la divergencia deliberada en vez de eliminar el
  determinismo del eval; el `SYSTEM_PROMPT`, el prompt de usuario y el parser
  siguen siendo exactamente los de producción.
- **Verificación:** revisión del docstring; no procede regresión de producto.

### C-03 — [ALTO] El cliente descartaba el mensaje de error del proveedor

- **Síntoma:** el cliente ignoraba el `error.message` que DeepInfra devuelve
  como `{"error": {"message": …}}` y traducía solo por código HTTP, así que
  «modelo inexistente» y «contexto excedido» llegaban idénticos como
  «El proveedor respondió HTTP 400.».
- **Promesa incumplida:** `docs/` describe que los fallos del proveedor se
  muestran al usuario de forma accionable; el código los colapsaba.
- **Clasificación:** defecto confirmado.
- **Corrección:** `provider_error_message` propaga el mensaje del proveedor con
  lectura acotada del cuerpo (8 KiB) y acotado del texto (500 caracteres), con
  fallback al mensaje por código ante cualquier desvío. Aplicado en los dos
  caminos de error del cliente (`llm.py`, streaming y no-streaming).
- **Prueba que falla antes y pasa después:**
  `tests/test_llm_http_contract.py::TestMensajeDeErrorDelProveedorContraServidorReal`
  (400 con mensaje, 400 sin mensaje, cuerpo no-JSON, acotado de longitud).

## 4. No verificado

- El comportamiento real de DeepInfra ante todos los códigos HTTP (solo se
  ejercitaron 400 con y sin cuerpo).
- La ejecución del flujo completo de UI contra red real.

## 5. Operaciones sin correspondencia

- Ninguna nueva; el transporte revisado ya estaba trazado en la serie anterior.

## 6. Estado

Corregidos y verificados C-01 a C-03. Gate verde: **780 pruebas, 0 omitidas,
cobertura 88.58 %**. `ruff` y `mypy` limpios.
