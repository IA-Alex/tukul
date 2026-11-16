"""Transporte HTTP compartido: opener de urllib que nunca sigue redirecciones.

`llm.py` y `threat_feed.py` abren conexiones salientes con `urllib`. En ambos
casos seguir un 3xx es peligroso:

- En `llm.py` urllib conserva `Authorization` / `x-api-key` al seguir el
  redirect y un endpoint comprometido podría redirigir a otro origen y robar la
  credencial.
- En `threat_feed.py` no hay credencial hoy, pero un 3xx podría saltar a otro
  host o a `http://` y colar una respuesta ajena como contexto; además, si en el
  futuro alguna fuente exige key, hereda este transporte sin sorpresas.

Devolver `None` en `redirect_request` convierte el 3xx en `HTTPError`, que llega
como error al llamador sin reenviar jamás cabeceras ni cambiar de origen.
"""
from __future__ import annotations

import errno
import http.client
import socket
import urllib.request
import xml.etree.ElementTree  # nosec B405 - uso endurecido: solo vía xml_fromstring_seguro
from typing import Any, Protocol


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Nunca sigue redirecciones HTTP(S)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Rechaza el seguimiento: devuelve None para que el 3xx llegue como error."""
        return None


# Sustituye el HTTPRedirectHandler por defecto de urlopen; el resto de handlers
# (proxy, HTTPS, etc.) se conservan vía build_opener().
NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


class SocketTracker(Protocol):
    """Quien recibe cada socket de conexión para poder cortarlo desde otro hilo."""

    def registrar_socket(self, socket_obj: Any) -> None: ...


class _CancellableSocket:
    """Envoltura de socket que se cancela sola al pedírselo desde otro hilo.

    `urllib` guarda el socket dentro de su conexión y lo usa tanto para enviar
    como para leer cabeceras y cuerpo. Sin esto, un `open()` colgado (servidor
    que acepta y no responde) solo termina al vencer `HTTP_TIMEOUT_SECONDS`.

    El hilo de la petición está BLOQUEADO dentro de `recv_into` mientras espera
    cabeceras, así que ninguna comprobación previa lo despierta: el corte tiene
    que venir de otro hilo. `cancel()` marca el evento y llama aquí a
    `cancelar()`, que hace `shutdown` sobre el socket real y desbloquea esa
    lectura con `OSError`. Comprobar el evento antes de cada operación evita
    además empezar a usar un socket ya cancelado.
    """

    def __init__(self, raw: Any, cancel_event: Any) -> None:
        self.__dict__["_raw"] = raw
        self.__dict__["_cancel_event"] = cancel_event

    def cancelar(self) -> None:
        """Corta el socket desde el hilo de la UI (no desde el de la petición).

        `shutdown` despierta al hilo bloqueado en `recv_into`; `close` libera el
        descriptor. `close` sin `shutdown` puede descartar el último ACK y dejar
        al servidor bloqueado escribiendo (el mismo motivo por el que
        `_read_capped` drena en lugar de cortar), así que van en este orden.
        """
        raw = self.__dict__["_raw"]
        try:
            raw.shutdown(socket.SHUT_RDWR)
        except (OSError, ValueError):
            pass
        try:
            raw.close()
        except (OSError, ValueError):
            pass

    def _comprobar(self) -> None:
        """Falla si la petición se canceló antes de esta operación."""
        if self._cancel_event is not None and self._cancel_event.is_set():
            self.cancelar()
            raise OSError(errno.ECANCELED, "La consulta se canceló.")

    def recv(self, *args: Any, **kwargs: Any) -> Any:
        """Lee datos; falla si la petición se canceló antes de empezar."""
        self._comprobar()
        return self._raw.recv(*args, **kwargs)

    def recv_into(self, *args: Any, **kwargs: Any) -> Any:
        """Lee datos en un buffer; es la lectura que usa `socket.makefile`.

        `SocketIO.readinto` llama a `recv_into`, no a `recv`, así que sin este
        método la lectura de cabeceras ni siquiera pasaba por la envoltura.
        El desbloqueo durante la espera lo hace `cancelar()` desde el hilo de la
        UI; aquí solo se impide empezar una lectura ya cancelada.
        """
        # El hilo de la petición está BLOQUEADO aquí esperando cabeceras; la
        # comprobación previa no puede desbloquearlo. El desbloqueo lo hace
        # `cancelar()` desde el hilo de la UI.
        return self._raw.recv_into(*args, **kwargs)

    def sendall(self, *args: Any, **kwargs: Any) -> Any:
        """Escribe; no empieza a enviar nada si ya se canceló."""
        self._comprobar()
        return self._raw.sendall(*args, **kwargs)

    def makefile(self, *args: Any, **kwargs: Any) -> Any:
        """Devuelve el fichero del socket sin envolver (bandeja de urllib)."""
        return self._raw.makefile(*args, **kwargs)

    def settimeout(self, value: Any) -> None:
        """El timeout lo fija urllib en `open()`; se delega tal cual."""
        self._raw.settimeout(value)

    def __getattr__(self, name: str) -> Any:
        """Todo lo demás (fileno, getpeername…) se delega al socket real."""
        return getattr(self.__dict__["_raw"], name)


def build_tracking_opener(
    tracker: SocketTracker, cancel_event: Any = None
) -> urllib.request.OpenerDirector:
    """Opener sin redirects que expone sus sockets para cortar un `open()` colgado.

    `NO_REDIRECT_OPENER` sirve para todo lo que no se cancela a mitad de
    conexión. Un cliente que sí debe poder cortar un `open()` bloqueado (el LLM,
    que puede esperar hasta `HTTP_TIMEOUT_SECONDS` mientras la UI ya dice
    «cancelado») necesita un opener propio: el registro del socket es estado de
    instancia, no de proceso.

    Cómo se engancha sin copiar la lógica de urllib: `urllib` obtiene las clases
    de conexión de estos dos handlers concretos (`http_class`/`https_class`) y
    las usa en su propio `do_open`, que construye header, proxy y TLS. Basta con
    que esas clases publiquen su socket al conectar.

    HTT(S)Connection crea `sock` dentro de `connect()`, no en el constructor: es
    el único punto en el que existe el objeto que hay que apagar mientras
    `getresponse()` espera cabeceras (el caso de un servidor que acepta la
    conexión y nunca responde).
    """

    class _Base:
        """Mixin que envuelve el socket recién establecido, sin más cambios.

        `urllib` construye sus conexiones con `http_class(host, ...)` POSICIONAL
        y el `do_open` heredado usa `super().do_open(http_class, ...)` pasando su
        propio `http_class`, que sigue siendo el estándar y recalcularía su
        `http_class`. Por eso las subclases de abajo sobrescriben `http_open` y
        `https_open` para usar estas clases: sin eso, este `connect()` nunca se
        ejecutaría y el socket quedaría sin registrar.
        """

        def connect(self) -> None:
            super().connect()  # type: ignore[misc]
            self._adoptar_socket()

        def _adoptar_socket(self) -> None:
            # `sock` nace dentro de `connect()`: es el único momento en el que
            # existe el objeto sobre el que bloqueará `getresponse()`.
            sock = getattr(self, "sock", None)
            if sock is None:
                return
            if cancel_event is not None:
                sock = _CancellableSocket(sock, cancel_event)
                setattr(self, "sock", sock)  # noqa: B010 - evita el chequeo de tipo de mypy
            tracker.registrar_socket(sock)

    class _TrackingHTTPConnection(_Base, http.client.HTTPConnection):
        pass

    class _TrackingHTTPSConnection(_Base, http.client.HTTPSConnection):
        pass

    class _TrackingHTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req: urllib.request.Request) -> Any:
            return self.do_open(_TrackingHTTPConnection, req)

    class _TrackingHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req: urllib.request.Request) -> Any:
            # El contexto TLS lo aporta la instancia; `do_open` lo espera como
            # argumento con nombre (igual que la implementación estándar).
            return self.do_open(
                _TrackingHTTPSConnection, req, context=getattr(self, "_context", None))

    return urllib.request.build_opener(
        _NoRedirectHandler(),
        _TrackingHTTPHandler(),
        _TrackingHTTPSHandler(),
    )


def xml_fromstring_seguro(body: bytes) -> xml.etree.ElementTree.Element:
    """Parsea XML de una fuente remota rechazando cualquier DTD.

    `xml.etree.ElementTree` es vulnerable a XXE y a la expansión exponencial de
    entidades («billion laughs») cuando el documento define un `<!DOCTYPE>`. Un
    cuerpo pequeño puede expandirse a gigabytes de memoria *durante* el parseo,
    así que el techo de bytes leído no protege por sí solo (bandit B314/B405).

    Todos esos ataques requieren una declaración de tipo de documento: las
    entidades se declaran en el subconjunto interno de un DOCTYPE o en un DTD
    externo referenciado desde él. Rechazar el documento si aparece un DOCTYPE
    los neutraliza por completo, sin depender de `defusedxml` (que no es una
    dependencia del proyecto) y de forma idéntica en CPython 3.11-3.13, cuyas
    APIs de parser difieren.

    Los feeds legítimos (Atom de arXiv, STIX de MITRE) no llevan DTD, así que la
    comprobación no afecta a las respuestas válidas.

    Raises:
        xml.etree.ElementTree.ParseError: si el documento trae DTD o no es XML.
    """
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise xml.etree.ElementTree.ParseError(
            "El XML de una fuente externa no puede declarar DTD ni entidades."
        )
    # Bandit B314/bandit B405 suprimidos: el DTD (único vector de XXE/billion
    # laughs) ya se rechazó arriba, así que esta llamada es segura. Ver
    # `xml_fromstring_seguro`.
    return xml.etree.ElementTree.fromstring(body)  # nosec B314
