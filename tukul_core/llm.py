from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO, Any

from .http_safety import build_tracking_opener
from .logging_config import setup_logging
from .models import LlmProfile
from .prompts import prompt_sistema

logger = setup_logging()

#: Compatibilidad: el nombre histórico `SYSTEM_PROMPT` es el prompt del modo
#: revisión, que es lo que veía todo llamador antes de `0.8.0`. Las peticiones
#: reales usan `prompt_sistema(modo)` (ver `_request`).
SYSTEM_PROMPT = prompt_sistema("revision")
HTTP_TIMEOUT_SECONDS = 90
# Reintentos ante fallos transitorios: una cuota agotada o un 5xx del proveedor
# no deben tumbar la consulta al primer golpe. Solo se reintenta la APERTURA de
# la conexión (nunca a mitad de un stream ya iniciado, para no duplicar texto).
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
MAX_HTTP_ATTEMPTS = 3  # 1 intento inicial + 2 reintentos
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 4.0
# Techo por línea SSE: un proveedor que emita un flujo sin saltos de línea no debe
# poder agotar la memoria del proceso.
MAX_SSE_LINE_BYTES = 1_048_576
# Techos para respuestas completas (no streaming): sin ellos, response.read()
# cargaba en memoria un cuerpo remoto arbitrariamente grande antes de validarlo.
# El máximo se deriva de max_output_tokens (≈3.2 caracteres por token, hasta 3
# bytes en UTF-8, y el JSON puede escaparlos) con margen para usage y metadatos.
BYTES_PER_OUTPUT_TOKEN = 16
MAX_BODY_OVERHEAD_BYTES = 64 * 1024
READ_CHUNK_BYTES = 64 * 1024
RESPONSE_TOO_LARGE_ERROR = "El proveedor devolvió una respuesta mayor de lo esperado."
ALLOWED_URL_SCHEMES = {"https", "http"}
# http:// solo se acepta contra loopback (Ollama y similares); hacia la red abriría
# la API key en claro.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
HTTP_ERROR_MESSAGES = {
    401: "La API key fue rechazada.", 403: "El proveedor rechazó el acceso.",
    404: "No se encontró el endpoint o modelo.", 408: "El proveedor agotó el tiempo de espera.",
    429: "Se alcanzó el límite de solicitudes o cuota.", 500: "El proveedor tuvo un error interno.",
    503: "El proveedor no está disponible temporalmente.",
}


@dataclass(frozen=True)
class ProviderSpec:
    """Especificación estática de un proveedor LLM y su protocolo."""

    identifier: str
    label: str
    endpoint_hint: str
    protocol: str = "openai_compatible"


# Proveedores disponibles. Todos usan protocolo compatible con OpenAI Chat
# Completions. Novita AI y DeepInfra son los dos habilitados.
PROVIDERS: dict[str, ProviderSpec] = {
    "openai_compatible": ProviderSpec("openai_compatible", "Compatible con OpenAI", "https://servidor/v1/chat/completions"),
    "deepinfra": ProviderSpec("deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai/chat/completions"),
    "novita": ProviderSpec("novita", "Novita AI", "https://api.novita.ai/v3/openai/chat/completions"),
}


def provider_spec(identifier: str) -> ProviderSpec:
    """Devuelve la especificación del proveedor; los desconocidos caen al compatible con OpenAI."""
    return PROVIDERS.get(identifier, PROVIDERS["openai_compatible"])


def http_error_message(status: int) -> str:
    """Traduce un código HTTP de error a un mensaje legible para el usuario."""
    return HTTP_ERROR_MESSAGES.get(status, f"El proveedor respondió HTTP {status}.")


# Techos para el cuerpo de un error HTTP: el proveedor solo aporta un mensaje
# corto, así que no se lee más allá de esto ni se confía en su forma.
MAX_ERROR_BODY_BYTES = 8 * 1024
MAX_ERROR_MESSAGE_CHARS = 500


def provider_error_message(error: urllib.error.HTTPError) -> str:
    """Mensaje del proveedor si lo trae; si no, la traducción por código.

    DeepInfra (y OpenAI-compatible en general) devuelve los fallos como
    ``{"error": {"message": …}}``. Descartarlo dejaba al usuario con
    «El proveedor respondió HTTP 400.» ante un «modelo inexistente» o un
    «contexto excedido», que son causas distintas que el status no distingue.
    El cuerpo se lee con techo (nunca se confía en su tamaño ni en su forma) y
    cualquier desvío cae al mensaje por código, sin filtrar contenido ajeno.
    """
    try:
        cuerpo = error.read(MAX_ERROR_BODY_BYTES)
    except (OSError, ValueError):
        return http_error_message(error.code)
    if not cuerpo:
        return http_error_message(error.code)
    try:
        datos = json.loads(cuerpo.decode("utf-8", errors="replace"))
    except ValueError:
        return http_error_message(error.code)
    detalle = datos.get("error") if isinstance(datos, dict) else None
    mensaje = detalle.get("message") if isinstance(detalle, dict) else None
    if not isinstance(mensaje, str) or not mensaje.strip():
        return http_error_message(error.code)
    return mensaje.strip()[:MAX_ERROR_MESSAGE_CHARS]


def estimate_prompt_tokens(system_prompt: str, json_payload: str) -> int:
    """
    Estima tokens del prompt COMPLETO (system + payload JSON que incluye todo).
    Usa 1 token ≈ 3.2 caracteres (conservador para español).
    El payload JSON ya incluye artículo, contexto, conversación con mensaje actual.
    """
    total_chars = len(system_prompt) + len(json_payload)
    # Aproximación conservadora: 1 token cada 3.2 caracteres (más conservador que 4)
    return max(1, int(total_chars / 3.2))


def gemini_url(endpoint: str, model: str, stream: bool) -> str:
    """Normaliza endpoint Gemini sin incluir secretos en la URL."""
    formatted = endpoint.format(model=model) if "{model}" in endpoint else endpoint
    parsed = urllib.parse.urlsplit(formatted)
    path = parsed.path
    if not stream:
        path = path.replace(":streamGenerateContent", ":generateContent")
    params = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if key not in {"key", "alt"}]
    if stream:
        params.append(("alt", "sse"))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, urllib.parse.urlencode(params), parsed.fragment))


class LlmError(RuntimeError):
    """Error de la capa LLM con mensaje comprensible para el usuario final."""
    pass


def validate_endpoint(endpoint: str) -> str:
    """Rechaza endpoints que sacarían la API key del transporte cifrado.

    Sin esta comprobación, un config.toml manipulado (o una errata) bastaba para
    enviar la credencial en claro a un host arbitrario, o para que urllib
    intentase esquemas como file:// o ftp:// con las cabeceras de autenticación.
    """
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise LlmError(
            "El endpoint debe ser una URL http(s) válida; revisa el perfil LLM."
        )
    if parsed.scheme == "http" and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise LlmError(
            "Solo se permite http:// hacia localhost. Usa https:// para no enviar "
            "la API key en claro."
        )
    return endpoint


# Opener sin redirects y con socket rastreado: urllib conservaría Authorization
# / x-api-key al seguir un 3xx y un endpoint comprometido podría redirigir a
# otro origen y robar la credencial; el rastreo del socket es lo que permite
# cortar un `open()` colgado (ver `LLMClient.cancel`). Cada instancia usa el
# suyo (`self._opener`). Este global sin rastreo se conserva para los tests que
# parchean la apertura HTTP y para quien importe el nombre histórico.
def _es_cancelacion_por_socket(error: BaseException, cancel_event: threading.Event | None) -> bool:
    """¿El fallo de E/S se debió a que la petición estaba cancelada?

    Un socket cortado por `cancel()` levanta OSError (EBADF, ECONNABORTED…) o
    ValueError (operación sobre un objeto cerrado). Con el evento marcado es una
    cancelación pedida; sin él, es un fallo real que debe llegar al usuario.
    `URLError` nunca cuenta: urllib lo usa para fallos de transporte reales.
    """
    if isinstance(error, urllib.error.URLError):
        return False
    return cancel_event is not None and cancel_event.is_set()


def _cortar_socket(socket_obj: Any) -> None:
    """Despierta a quien esté bloqueado en el socket y lo cierra.

    `shutdown` es lo que desbloquea un `recv` en curso (otro hilo esperando
    cabeceras); `close` libera el descriptor. Ambos pueden fallar si el socket
    ya estaba cerrado por el otro extremo, y eso no es un error que importe.
    """
    apagar = getattr(socket_obj, "shutdown", None)
    if callable(apagar):
        try:
            apagar(socket.SHUT_RDWR)
        except (OSError, ValueError):
            pass
    cerrar = getattr(socket_obj, "close", None)
    if callable(cerrar):
        try:
            cerrar()
        except (OSError, ValueError):
            pass


class _SinRastreo:
    """Tracker del opener global: no corta sockets por sí solo.

    Una petición sin evento de cancelación no necesita cortar nada; cuando sí lo
    necesita, se construye un opener propio con el tracker del cliente
    (`LLMClient._con_opener`).
    """

    def registrar_socket(self, socket_obj: Any) -> None:
        """No hace nada: el opener global no pertenece a ninguna petición."""


_OPENER_NO_REDIRECT = build_tracking_opener(_SinRastreo())


def _abrir_una_vez(opener: Any, request: Any) -> Any:
    """Hace un único `open()` (sin reintentos).

    Aparte de `_open_with_retry` para que la función de reintentos quepa en la
    complejidad ciclomática que exige el linter (C901). No toca `request`: la
    validación y el `timeout` los aplica urllib dentro de `OpenerDirector.open`,
    y así un `open` parcheado en pruebas sigue controlando la apertura.
    """
    # Sin `timeout` explícito: `OpenerDirector.open` inspecciona la petición
    # (`req.timeout`, `req.type`…) antes de delegar, y los dobles de prueba pasan
    # objetos mínimos. urllib aplica el suyo propio por defecto.
    return opener.open(request)  # nosec B310


@dataclass
class LlmResponse:
    """Respuesta completa (no streaming) de un proveedor LLM."""

    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ToolCall:
    """Petición de ejecución incluida en una respuesta del proveedor.

    Tukul no expone herramientas al modelo. Este tipo existe para poder
    ignorarlas de forma explícita: sin él, una respuesta con `tool_calls` se
    trata como texto vacío (`content: null`) y parece un fallo del proveedor.
    """

    id: str
    name: str


@dataclass
class StreamChunk:
    """Fragmento incremental de una respuesta en streaming."""

    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Tukul no le da herramientas al modelo: si llega una petición de ejecución
    # se ignora de forma explícita (y se deja constancia), nunca se ejecuta ni
    # se pinta como si fuera texto.
    tool_calls: tuple[ToolCall, ...] = ()


class LLMClient:
    """Cliente HTTP para proveedores LLM, con reintentos y límites de seguridad."""

    def __init__(self) -> None:
        # Solo se guarda para poder cerrarlo desde otro hilo (cancelación).
        self._responses: dict[int, IO[bytes]] = {}
        self._response_lock = threading.Lock()
        # Opener propio con socket rastreado: es lo que permite que Cancelar
        # corte también la fase de `open()`, no solo una respuesta ya abierta.
        self._opener = _OPENER_NO_REDIRECT
        # Con qué opener nació esta instancia. Solo sirve para detectar que se
        # sustituyó el global y no debe salir a red real por el camino viejo.
        self._opener_original = self._opener
        # Sockets vivos, cada uno con el hilo que lo abrió: la UI corta desde
        # otro hilo y la petición limpia al volver de su propio `open()`.
        self._sockets: list[tuple[Any, int]] = []
        self._socket_lock = threading.Lock()

    def registrar_socket(self, socket_obj: Any) -> None:
        """Guarda un socket recién conectado (lo llama el opener)."""
        with self._socket_lock:
            ahora = threading.get_ident()
            # El hilo de la petición puede volver de `open()` y limpiar mientras
            # este registro seguía en curso: un socket que llega tarde no debe
            # quedar huérfano en la lista ni sobrevivir a su petición.
            self._sockets = [
                (socket, hilo) for socket, hilo in self._sockets if hilo == ahora
            ]
            self._sockets.append((socket_obj, ahora))

    def _olvidar_sockets_en_vuelo(self) -> None:
        """Olvida los sockets del hilo actual (su `open()` ya terminó)."""
        ahora = threading.get_ident()
        with self._socket_lock:
            self._sockets = [
                (socket, hilo) for socket, hilo in self._sockets if hilo != ahora
            ]

    def _sincronizar_opener_parcheado(self) -> None:
        """Respeta un parche de pruebas sobre el opener global.

        Los tests sustituyen `_OPENER_NO_REDIRECT.open` para simular la red sin
        abrir conexiones reales. `opener.open` es un atributo de instancia
        (mock), no de la clase, así que hay que sustituir el objeto entero: por
        eso el módulo reconstruye el global al importar `urllib.request` y aquí
        solo se detecta que cambió de identidad.
        """
        global _OPENER_NO_REDIRECT
        if _OPENER_NO_REDIRECT is not self._opener_original:
            self._opener = _OPENER_NO_REDIRECT

    def cancel(self, request_id: int) -> None:
        """Cierra el stream activo y corta la conexión en curso, si la hay.

        Antes solo cerraba una respuesta ya abierta: mientras `open()` estaba
        conectando o esperando cabeceras (hasta `HTTP_TIMEOUT_SECONDS`), Cancelar
        no tenía nada que cerrar y la UI prometía una cancelación que podía
        tardar hasta 90 s. Ahora también se apagan los sockets en vuelo:
        `shutdown` despierta al hilo bloqueado en `recv` y `close` libera el
        descriptor. No se corta a la mitad de una escritura grande para no
        dejarlo en estado inconsistente; `shutdown` ya es suficiente para
        desbloquear.
        """
        with self._response_lock:
            response = self._responses.pop(request_id, None)
        with self._socket_lock:
            sockets = [socket for socket, _hilo in self._sockets]
            self._sockets = []
        if response is not None:
            try:
                response.close()
            except OSError:
                pass
        for socket_obj in sockets:
            cancelar = getattr(socket_obj, "cancelar", None)
            if callable(cancelar):
                cancelar()
            else:
                _cortar_socket(socket_obj)

    def _con_opener(self, cancel_event: threading.Event | None) -> Any:
        """Opener a usar en esta petición, con el evento de cancelación dentro.

        El rastreo de socket y la cancelación viven en el opener, así que uno
        ligado a OTRO evento no sirve: se construye uno para este. Sin evento se
        usa el de la instancia, que es `_OPENER_NO_REDIRECT`: el mismo objeto
        que la suite parchea para simular la red, de modo que un parche sigue
        teniendo efecto sin tocar los tests.
        """
        self._sincronizar_opener_parcheado()
        if cancel_event is None:
            return self._opener
        return build_tracking_opener(self, cancel_event)

    @staticmethod
    def _retry_delay(attempt: int, error: BaseException | None) -> float:
        """Segundos de espera antes de reintentar, respetando `Retry-After`.

        `attempt` es el número de reintento que se va a hacer (1 = el primero).
        Si el proveedor manda `Retry-After` (segundos), ese valor manda; si no,
        se usa un backoff exponencial acotado por `BACKOFF_MAX_SECONDS`.
        """
        headers = getattr(error, "headers", None)
        retry_after: object = (headers or {}).get("Retry-After")
        if isinstance(retry_after, (int, float)):
            return min(max(float(retry_after), 0.0), BACKOFF_MAX_SECONDS)
        if isinstance(retry_after, str):
            try:
                return min(max(float(retry_after), 0.0), BACKOFF_MAX_SECONDS)
            except ValueError:
                pass
        return min(BACKOFF_BASE_SECONDS * (2.0 ** (attempt - 1)), BACKOFF_MAX_SECONDS)

    def _open_with_retry(self, request: urllib.request.Request, cancel_event: threading.Event | None = None) -> Any:
        """Abre la conexión HTTP reintentando solo errores transitorios.

        Devuelve la respuesta abierta, o None si se canceló durante una espera.
        Los errores no reintentables (401/403/404…) y el agotamiento de los
        reintentos se relanzan tal cual para que `stream`/`complete` los
        traduzcan al mensaje humano.
        """
        attempt = 0
        ultimo_error: BaseException | None = None
        # Un solo opener para todos los intentos: si el socket se canceló, su
        # evento sigue marcado y el siguiente intento lo respeta igual.
        opener = self._con_opener(cancel_event)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return None
            try:
                respuesta = _abrir_una_vez(opener, request)
                # `open()` volvió: el socket ya es trabajo de `_responses`, no
                # del registro de conexiones en vuelo.
                self._olvidar_sockets_en_vuelo()
                return respuesta
            except urllib.error.HTTPError as error:
                ultimo_error = error
                if error.code not in RETRYABLE_STATUS:
                    raise
            except (urllib.error.URLError, OSError, ValueError) as error:
                ultimo_error = error
                if _es_cancelacion_por_socket(error, cancel_event):
                    # Socket cortado por `cancel()`: cancelación pedida, no fallo.
                    return None
            if attempt >= MAX_HTTP_ATTEMPTS - 1:
                break
            attempt += 1
            if self._esperar_reintento(attempt, ultimo_error, cancel_event):
                return None  # cancelada mientras esperaba
        if ultimo_error is not None:
            raise ultimo_error
        raise LlmError("No se pudo conectar con el proveedor.")

    def _esperar_reintento(
        self, attempt: int, error: BaseException | None, cancel_event: threading.Event | None
    ) -> bool:
        """Espera antes del reintento. True si se canceló durante la espera.

        `time.sleep` no es interrumpible: el botón Cancelar parecía muerto hasta
        4 s por intento. `wait` despierta en cuanto se cancela.
        """
        espera = self._retry_delay(attempt, error)
        if cancel_event is None:
            time.sleep(espera)
            return False
        return cancel_event.wait(espera)

    def _request(self, profile: LlmProfile, api_key: str, prompt: str, stream: bool,
                 modo: str | None = None) -> urllib.request.Request:
        sistema = prompt_sistema(modo)
        spec = provider_spec(profile.provider)
        if spec.protocol == "anthropic_messages":
            endpoint = validate_endpoint(profile.endpoint)
            payload = {"model": profile.model, "max_tokens": profile.max_output_tokens, "system": sistema, "messages": [{"role": "user", "content": prompt}], "stream": stream}
            headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01", "Accept": "text/event-stream" if stream else "application/json"}
            return urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        if spec.protocol == "gemini_generate_content":
            endpoint = validate_endpoint(gemini_url(profile.endpoint, profile.model, stream))
            payload = {"systemInstruction": {"parts": [{"text": sistema}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": profile.max_output_tokens, "temperature": profile.temperature}}
            headers = {"Content-Type": "application/json", "x-goog-api-key": api_key, "Accept": "text/event-stream" if stream else "application/json"}
            return urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        endpoint = validate_endpoint(profile.endpoint)
        payload = {"model": profile.model, "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}], "max_tokens": profile.max_output_tokens, "temperature": profile.temperature, "stream": stream}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        if stream:
            headers["Accept"] = "text/event-stream"
        return urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")

    @staticmethod
    def _declared_too_large(response: Any, max_bytes: int) -> bool:
        """True si `Content-Length` ya anuncia un cuerpo por encima del techo."""
        headers = getattr(response, "headers", None)
        declared = headers.get("Content-Length") if headers is not None else None
        if declared is None:
            return False
        try:
            return int(declared) > max_bytes
        except (TypeError, ValueError):
            return False  # Malformado: el techo se aplica al leer.

    @staticmethod
    def _read_capped(read: Any, max_bytes: int) -> bytes:
        """Lee por tramos, drenando (sin acumular) lo que excede el techo.

        Al superar el techo no se corta la lectura: se drena el resto y después
        se lanza el error. Cerrar el socket a medias dejaba al servidor
        bloqueado escribiendo un cuerpo que nadie lee, y eso colgó el cierre del
        servidor en las pruebas de contrato.
        """
        chunks: list[bytes] = []
        total = 0
        excedido = False
        while True:
            chunk = read(min(READ_CHUNK_BYTES, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                excedido = True
            elif not excedido:
                chunks.append(chunk)
        if excedido:
            raise LlmError(RESPONSE_TOO_LARGE_ERROR)
        return b"".join(chunks)

    @staticmethod
    def _read_bounded(response: Any, max_output_tokens: int) -> bytes:
        """Lee una respuesta completa (no streaming) con techo de memoria.

        Content-Length se prevalida contra el máximo derivado de
        max_output_tokens y el cuerpo se lee por tramos, abortando en cuanto se
        supera: un proveedor defectuoso (o un endpoint personalizado) no puede
        agotar la memoria del proceso.
        """
        max_bytes = MAX_BODY_OVERHEAD_BYTES + max_output_tokens * BYTES_PER_OUTPUT_TOKEN
        if LLMClient._declared_too_large(response, max_bytes):
            # `with response:` del llamador cierra la conexión: aquí no se lee
            # ni un byte, y el servidor no puede haber enviado nada aún.
            raise LlmError(RESPONSE_TOO_LARGE_ERROR)
        read = getattr(response, "read", None)
        if read is None:
            # Dobles de prueba y proveedores atípicos sin read(): se acota igual.
            partes = []
            total = 0
            for chunk in response:
                total += len(chunk)
                if total > max_bytes:
                    raise LlmError(RESPONSE_TOO_LARGE_ERROR)
                partes.append(chunk)
            return b"".join(partes)
        return LLMClient._read_capped(read, max_bytes)

    @staticmethod
    def _iter_lines(response: Any) -> Iterator[bytes]:
        """Itera líneas SSE con techo de memoria por línea.

        Cae a la iteración simple cuando el objeto de respuesta no expone
        readline (dobles de prueba y proveedores atípicos).
        """
        readline = getattr(response, "readline", None)
        if readline is None:
            yield from response
            return
        while True:
            raw = readline(MAX_SSE_LINE_BYTES)
            if not raw:
                return
            yield raw

    @staticmethod
    def _sse_payload(raw: bytes) -> str | None:
        """Extrae el cuerpo de una línea `data:` SSE. None si la línea no lo es."""
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            return None
        return line[5:].strip()

    @staticmethod
    def _usage(event: dict) -> tuple[int | None, int | None]:
        usage = event.get("usage") or event.get("usageMetadata") or {}
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("promptTokenCount")
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("outputTokenCount") or usage.get("candidatesTokenCount")
        return input_tokens, output_tokens

    def _stream_event(self, profile: LlmProfile, event: dict) -> StreamChunk:
        protocol = provider_spec(profile.provider).protocol
        if protocol == "anthropic_messages":
            content = event.get("delta", {}).get("text", "") if event.get("type") == "content_block_delta" else ""
        elif protocol == "gemini_generate_content":
            candidates = event.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        else:
            delta = (event.get("choices") or [{}])[0].get("delta") or {}
            content = delta.get("content") or ""
            llamadas = tuple(
                ToolCall(str(item.get("id") or ""), str((item.get("function") or {}).get("name") or ""))
                for item in delta.get("tool_calls") or ()
                if isinstance(item, dict)
            )
        input_tokens, output_tokens = self._usage(event)
        return StreamChunk(content, input_tokens, output_tokens, llamadas)

    def _consume_sse(self, profile: LlmProfile, response: Any, cancel_event: threading.Event | None) -> Iterator[StreamChunk]:
        """Traduce el cuerpo SSE en StreamChunk, saltando líneas ilegibles."""
        for raw in self._iter_lines(response):
            if cancel_event is not None and cancel_event.is_set():
                return
            data = self._sse_payload(raw)
            if data is None:
                continue
            if data == "[DONE]":
                return
            try:
                chunk = self._stream_event(profile, json.loads(data))
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            if chunk.tool_calls:
                # Defensa en profundidad: una respuesta que intenta pedir
                # herramientas no activa nada. Se ve en el log de diagnóstico.
                logger.warning(
                    "Respuesta con %d petición(es) de herramienta ignorada(s); "
                    "Tukul no expone herramientas al modelo", len(chunk.tool_calls))
            if chunk.content or chunk.input_tokens is not None or chunk.output_tokens is not None:
                yield chunk

    def stream(self, profile: LlmProfile, api_key: str, prompt: str, request_id: int | None = None, cancel_event: threading.Event | None = None, modo: str | None = None) -> Iterator[StreamChunk]:
        """Abre la respuesta del proveedor en streaming y emite sus eventos SSE.

        La cancelación es cooperativa (`cancel_event`) y los reintentos solo
        ocurren en la apertura de la conexión, nunca a mitad de un stream.
        `modo` elige el prompt de sistema (ver `tukul_core.prompts`).
        """
        if not profile.enabled or not api_key:
            raise LlmError("Configura endpoint, modelo y API key.")
        request = self._request(profile, api_key, prompt, stream=True, modo=modo)
        try:
            response = self._open_with_retry(request, cancel_event)
            if response is None:
                return  # Cancelada durante una espera de reintento: nadie espera respuesta.
            with response:
                if request_id is not None:
                    with self._response_lock:
                        self._responses[request_id] = response
                # La cancelación puede haber ocurrido durante la apertura HTTP.
                if cancel_event is not None and cancel_event.is_set():
                    response.close()
                    return
                yield from self._consume_sse(profile, response, cancel_event)
        except urllib.error.HTTPError as error:
            raise LlmError(provider_error_message(error)) from error
        except urllib.error.URLError as error:
            raise LlmError("No se pudo conectar con el proveedor.") from error
        except (OSError, ValueError) as error:
            if cancel_event is not None and cancel_event.is_set():
                return
            raise LlmError("La conexión de streaming se interrumpió.") from error
        finally:
            if request_id is not None:
                with self._response_lock:
                    self._responses.pop(request_id, None)
    def complete(self, profile: LlmProfile, api_key: str, prompt: str,
                 modo: str | None = None,
                 cancel_event: threading.Event | None = None) -> LlmResponse:
        """Solicita una respuesta completa (no streaming) y la devuelve parseada.

        El cuerpo se lee con techo de memoria coherente con `max_output_tokens`
        y las redirecciones HTTP se rechazan para no reenviar la API key.
        `modo` elige el prompt de sistema (ver `tukul_core.prompts`); sin él se
        conserva el comportamiento histórico (revisión).

        `cancel_event` es opcional y hace `complete` cancelable igual que
        `stream`: sin él, el backoff caía en `time.sleep`, no interrumpible, y
        una cancelación durante la espera entre reintentos no se notaba hasta
        que terminaba (hasta 4 s por intento). Quien no lo pase conserva el
        comportamiento anterior.
        """
        if not profile.enabled or not api_key:
            raise LlmError("Configura endpoint, modelo y API key.")
        request = self._request(profile, api_key, prompt, stream=False, modo=modo)
        try:
            response = self._open_with_retry(request, cancel_event)
            if response is None:
                # Cancelada durante una espera de reintento: no hay respuesta
                # que devolver ni error que mostrar, igual que en `stream`.
                raise LlmError("La consulta se canceló.")
            with response:
                data = json.loads(self._read_bounded(response, profile.max_output_tokens).decode())
            protocol = provider_spec(profile.provider).protocol
            if protocol == "anthropic_messages": content = "".join(part.get("text", "") for part in data.get("content", []) if isinstance(part, dict))
            elif protocol == "gemini_generate_content": content = "".join(part.get("text", "") for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []) if isinstance(part, dict))
            else: content = data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as error:
            raise LlmError(provider_error_message(error)) from error
        except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LlmError("No se pudo obtener una respuesta válida del proveedor.") from error
        if not isinstance(content, str) or not content.strip():
            raise LlmError("El proveedor devolvió una respuesta vacía.")
        input_tokens, output_tokens = self._usage(data) if isinstance(data, dict) else (None, None)
        return LlmResponse(content, input_tokens, output_tokens)
