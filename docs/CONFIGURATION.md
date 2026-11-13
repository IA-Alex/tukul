# Configuración

La configuración canónica es `config.toml`, por defecto `~/.config/tukul/config.toml`; `--config RUTA` selecciona otro archivo. Se carga defensivamente: TOML ilegible usa el perfil `default`; perfiles individuales inválidos se ignoran y se registra un warning.

## Estructura

```toml
[llm]
active_profile = "deepinfra"

[profiles.deepinfra]
provider = "deepinfra"
endpoint = "https://api.deepinfra.com/v1/openai/chat/completions"
model = "modelo-del-proveedor"
api_key_env = "DEEPINFRA_API_KEY"
max_output_tokens = 1000
max_context_chars = 48000
max_total_model_tokens = 128000
temperature = 0.5
```

Cada entrada bajo `profiles.<name>` crea un `LlmProfile`. `name` se deriva de la tabla y no es un campo TOML. Campos desconocidos se ignoran.

| KEY | TYPE | REQUIRED | DEFAULT | VALID_RANGE / behavior | PROVIDER_APPLICABILITY | SECURITY_IMPACT | EXAMPLE |
|---|---|---|---|---|---|---|---|
| `llm.active_profile` | string | no | `default` | si no existe, usa `default` | todos | selecciona qué key/env se usa | `deepinfra` |
| `provider` | string | no | `disabled` | valores UI: `openai_compatible`, `deepinfra`, `novita`; desconocido cae a compatible | todos | determina protocolo y headers | `openai_compatible` |
| `endpoint` | string | no | `""` | URL `https`; `http` solo loopback | todos | se valida antes de enviar key | `https://...` |
| `model` | string | no | `""` | nombre del modelo/proveedor | todos | forma parte del request | `modelo-del-proveedor` |
| `api_key_env` | string | no | `""` | nombre de variable; vacío deja el perfil sin key salvo sesión/keyring | todos | evita serializar el secreto | `DEEPINFRA_API_KEY` |
| `max_output_tokens` | integer | no | `1000` | 1..16000 | todos | limita salida y techo de memoria | `1000` |
| `max_context_chars` | integer | no | `48000` | mínimo 100 | todos | limita contenido local enviado | `48000` |
| `max_total_model_tokens` | integer | no | `128000` | >= `max_output_tokens` | todos | reserva entrada + salida | `128000` |
| `temperature` | number | no | `0.5` | 0.0..2.0 | todos; adaptador puede aplicarlo | afecta salida del proveedor | `0.5` |
| `input_price_per_million` | number | no | `0.0` | >= 0 | informativo/coste | no es secreto | `0.0` |
| `output_price_per_million` | number | no | `0.0` | >= 0 | informativo/coste | no es secreto | `0.0` |

DeepInfra, Novita AI y OpenAI-compatible usan Chat Completions. Timeout HTTP: 90 s. Apertura: hasta 3 intentos para 408, 429, 5xx y errores de conexión, con backoff y `Retry-After`; no se reintenta un stream ya iniciado.

Un campo con el tipo equivocado no se ignora en silencio. El perfil se carga con el valor por defecto de ese campo, se registra un aviso en el log y `tukul --health` lo lista junto al componente `llm`, con el perfil, el campo y el valor recibido. Ejemplo: `max_output_tokens = "4096"` (texto) se rechaza y el perfil usa `1000`; `max_output_tokens = 4096.0` (número sin parte decimal) se acepta como `4096`. Los booleanos nunca se aceptan como números.

`config.toml` y `estado.json` no contienen API keys. La prioridad de credenciales y las restricciones de endpoint están en [SECURITY.md](SECURITY.md).
