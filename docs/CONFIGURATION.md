# Configuración

La configuración canónica es `config.toml`, por defecto `~/.config/articulador/config.toml`; `--config RUTA` selecciona otro archivo. Se carga defensivamente: TOML ilegible usa el perfil `default`; perfiles individuales inválidos se ignoran y se registra un warning.

## Estructura

```toml
[llm]
active_profile = "deepseek"

[profiles.deepseek]
provider = "deepseek"
endpoint = "https://api.deepseek.com/chat/completions"
model = "modelo-del-proveedor"
api_key_env = "DEEPSEEK_API_KEY"
max_output_tokens = 1000
max_context_chars = 48000
max_total_model_tokens = 128000
temperature = 0.5
```

Cada entrada bajo `profiles.<name>` crea un `LlmProfile`. `name` se deriva de la tabla y no es un campo TOML. Campos desconocidos se ignoran.

| KEY | TYPE | REQUIRED | DEFAULT | VALID_RANGE / behavior | PROVIDER_APPLICABILITY | SECURITY_IMPACT | EXAMPLE |
|---|---|---|---|---|---|---|---|
| `llm.active_profile` | string | no | `default` | si no existe, usa `default` | todos | selecciona qué key/env se usa | `deepseek` |
| `provider` | string | no | `disabled` | valores UI: `openai_compatible`, `deepinfra`, `deepseek`, `openrouter`, `ollama`, `anthropic`, `gemini`; desconocido cae a compatible | todos | determina protocolo y headers | `ollama` |
| `endpoint` | string | no | `""` | URL `https`; `http` solo loopback | todos | se valida antes de enviar key | `https://...` |
| `model` | string | no | `""` | nombre del modelo/proveedor | todos | forma parte del request | `modelo-del-proveedor` |
| `api_key_env` | string | no | `""` | nombre de variable; vacío deja el perfil sin key salvo sesión/keyring | todos | evita serializar el secreto | `DEEPSEEK_API_KEY` |
| `max_output_tokens` | integer | no | `1000` | 1..16000 | todos | limita salida y techo de memoria | `1000` |
| `max_context_chars` | integer | no | `48000` | mínimo 100 | todos | limita contenido local enviado | `48000` |
| `max_total_model_tokens` | integer | no | `128000` | >= `max_output_tokens` | todos | reserva entrada + salida | `128000` |
| `temperature` | number | no | `0.5` | 0.0..2.0 | todos; adaptador puede aplicarlo | afecta salida del proveedor | `0.5` |
| `input_price_per_million` | number | no | `0.0` | >= 0 | informativo/coste | no es secreto | `0.0` |
| `output_price_per_million` | number | no | `0.0` | >= 0 | informativo/coste | no es secreto | `0.0` |

OpenAI-compatible, DeepInfra, DeepSeek, OpenRouter y Ollama usan Chat Completions; Anthropic usa Messages y Gemini usa Generate Content. Gemini puede interpolar `{model}` en su endpoint y añade la key en header, no en la URL. Timeout HTTP: 90 s. Apertura: hasta 3 intentos para 408, 429, 5xx y errores de conexión, con backoff y `Retry-After`; no se reintenta un stream ya iniciado.

`config.toml` y `estado.json` no contienen API keys. La prioridad de credenciales y las restricciones de endpoint están en [SECURITY.md](SECURITY.md).
