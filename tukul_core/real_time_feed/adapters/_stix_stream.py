"""Extracción incremental de objetos STIX de un bundle grande.

El bundle `enterprise-attack.json` pesa ~49 MB y tiene la forma
`{"objects": [ {...}, {...}, ... ]}`. Parsearlo entero con `json.loads`
materializa el árbol completo (decenas de MB) además del cuerpo crudo, y en la
práctica solo un puñado de objetos son técnicas (`attack-pattern`).

Este módulo recorre el cuerpo por tramos y devuelve cada objeto de `objects` en
cuanto está completo, usando `json.JSONDecoder.raw_decode` sobre un búfer
deslizante. Durante la extracción el búfer nunca contiene más de un objeto (más
el resto del tramo pendiente), así que el pico de memoria queda acotado por el
objeto más grande, no por el bundle entero.

La cabecera (hasta el `[` de `objects`) sí se acumula entera mientras se busca
la llave: un bundle real la declara en los primeros KB, así que en la práctica
solo se retienen unos pocos tramos. Conservarla completa es lo que permite
distinguir un JSON válido *sin* lista `objects` (bundle vacío → sin objetos) de
un cuerpo ilegible (→ `StixStreamError`) cuando la respuesta se agota.

El escaneo de la llave `"objects"` y del `[` es deliberadamente literal y solo
se aplica a la cabecera; los objetos se extraen con el decodificador JSON real,
que respeta comillas, escapes y anidamiento. No se interpreta nada a mano más
allá de localizar el inicio de la lista.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

MARKER = b'"objects"'
READ_CHUNK_BYTES = 64 * 1024

# Techo del búfer que `_es_json_valido` puede materializar con `json.loads`.
# Un bundle legítimo declara `objects` en los primeros KB, así que solo se llega
# al fallback de «JSON válido sin lista» con un cuerpo pequeño (`{}`,
# `{"foo": 1}`, …). Un cuerpo hostil sin `objects` acumularía hasta `max_bytes`
# (64 MB) en el búfer y luego lo materializaría entero en el parseo; con este
# techo se descarta como ilegible sin construir el árbol. El valor deja margen
# de sobra sobre cualquier cabecera real de bundle.
MAX_HEADER_BYTES = 1 * 1024 * 1024

# Estados del reconocimiento de la clave raíz `"objects"`.
_CORCHETE = 0  # ya está el `[` que abre la lista
_INCOMPLETO = 1  # la secuencia clave:`objects`:[ aún no está completa
_NO_LLAVE = 2  # no es la clave raíz (otra clave, un valor, o no hay clave)

_ESPACIOS = (b" ", b"\t", b"\r", b"\n")


class StixStreamError(RuntimeError):
    """El cuerpo no tiene la forma esperada de un bundle STIX."""


def iter_stix_objects(response: Any, max_bytes: int) -> Iterator[dict]:
    """Itera los objetos de `data.objects` sin materializar el bundle completo.

    Args:
        response: Objeto con `read(n)` que devuelve bytes hasta agotarse.
        max_bytes: Techo de bytes leídos; si se supera, se lanza
            `StixStreamError` (nunca se lee el resto sin límite).

    Yields:
        Cada objeto (dict) de la lista `objects`, en orden.

    Raises:
        StixStreamError: si el cuerpo no es un bundle válido, si excede
            `max_bytes`, o si contiene un JSON malformado.
    """
    decoder = _Decoder()
    total = 0
    buffer = bytearray()

    def leer() -> bytes:
        """Lee el siguiente tramo, respetando el techo de bytes."""
        nonlocal total, buffer
        chunk: bytes = response.read(READ_CHUNK_BYTES)
        if not chunk:
            return chunk
        total += len(chunk)
        if total > max_bytes:
            raise StixStreamError(
                "La respuesta de MITRE ATT&CK supera el límite de bytes."
            )
        buffer.extend(chunk)
        return chunk

    # Fase 1: localizar `"objects"` y el `[` de la lista.
    while True:
        if _encontrar_inicio_lista(buffer):
            break
        if not leer():
            # El cuerpo se agotó sin lista `objects`. Se distingue un bundle
            # legítimo SIN objetos (JSON válido: `{}`, `{"foo": 1}`, …) de un
            # cuerpo ilegible. El primero debe degradar a vacío —así lo hacía el
            # `data.get("objects", [])` anterior y lo fija
            # `test_un_json_no_objeto_no_rompe_el_tipo_de_objects`—; el segundo
            # sí es un error real. Un búfer por encima de `MAX_HEADER_BYTES` no
            # puede ser ninguna de las dos formas legítimas (una cabecera con
            # `objects` habría salido del bucle mucho antes), así que se rechaza
            # sin materializarlo con `json.loads`.
            if len(buffer) <= MAX_HEADER_BYTES and _es_json_valido(buffer):
                return
            raise StixStreamError("El bundle STIX no contiene una lista 'objects'.")

    # Fase 2: extraer objetos uno a uno.
    yield from decoder.iter_objects(buffer, leer)


def _encontrar_inicio_lista(buffer: bytearray) -> bool:
    """Recorta el búfer hasta dejar solo lo que sigue al `[` de `"objects"`.

    Devuelve True cuando la llave raíz y su `[` ya están en el búfer (y lo deja
    posicionado justo después). Sin la llave aún, devuelve False sin consumir.

    El escaneo es **estructural**, no una simple búsqueda de bytes: localiza la
    clave `"objects"` *fuera de cadenas* y *a profundidad de llave 1* (dentro del
    objeto raíz). Una búsqueda literal de `"objects"` encontraba la primera
    aparición en cualquier parte: si un objeto del bundle declaraba antes una
    clave anidada `"objects"`, se extraía esa lista y se perdían los objetos de
    la raíz (bundle JSON válido, silenciosamente mal leído). En el bundle real de
    MITRE la raíz va primero, pero el parser no debe depender de ese orden.

    Se ignoran los contenidos de cadena (comillas con escape `\\`) para no
    confundir un valor `"objects"` con la clave. Los bytes multibyte de UTF-8 no
    coinciden con `"`, `\\`, `{`, `}` ni `[`, así que el escaneo por bytes es
    seguro para la estructura.

    Cuando la llave no aparece, el búfer se conserva intacto: si el cuerpo se
    agota sin `objects`, hace falta completo para decidir si es un JSON válido
    sin objetos (→ vacío) o un cuerpo ilegible (→ error). El costo es nulo en el
    camino normal: un bundle real declara `objects` en los primeros KB, así que
    el bucle sale antes de acumular nada grande.
    """
    i = 0
    profundidad = 0
    en_cadena = False
    n = len(buffer)
    while i < n:
        byte = buffer[i]
        if en_cadena:
            if byte == 0x5C:  # barra invertida: el siguiente byte es literal
                i += 2
                continue
            if byte == 0x22:  # comilla de cierre
                en_cadena = False
            i += 1
            continue
        if byte == 0x22:  # comilla de apertura
            estado, corchete = _clave_objects_en_raiz(buffer, i, profundidad)
            if estado == _CORCHETE:
                del buffer[: corchete + 1]
                return True
            if estado == _INCOMPLETO:
                # La forma clave:`objects`:[ aún no está completa en el búfer:
                # conviene seguir leyendo sin consumir nada.
                return False
            # Sin clave todavía (o valor `"objects"`): se trata como cadena.
            en_cadena = True
            i += 1
            continue
        if byte == 0x7B:  # {
            profundidad += 1
        elif byte == 0x7D:  # }
            profundidad -= 1
        i += 1
    return False


def _clave_objects_en_raiz(
    buffer: bytearray, i: int, profundidad: int
) -> tuple[int, int]:
    """Decide si la comilla en `i` abre la clave `"objects"` de la raíz.

    Devuelve `(_CORCHETE, idx)` con el `[` de la lista si es esa clave y ya está
    completa; `(_INCOMPLETO, -1)` si la forma `clave:`objects`:[` aún no cabe en
    el búfer; y `(_NO_LLAVE, -1)` si no es la clave raíz (otra clave, un valor,
    o no estamos a profundidad 1). Reconoce la clave solo *fuera* de cadenas y a
    profundidad 1 (dentro del objeto raíz).
    """
    if profundidad != 1 or not buffer.startswith(MARKER, i):
        return _NO_LLAVE, -1
    return _corchete_tras_llave(buffer, i + len(MARKER))


def _corchete_tras_llave(buffer: bytearray, desde: int) -> tuple[int, int]:
    """Estado e índice del `[` que abre la lista de una clave `"objects"`.

    Tras la clave `"objects"` debe venir `:`, espacios opcionales y `[`. Devuelve
    `(_CORCHETE, indice)` si el `[` ya está; `(_INCOMPLETO, -1)` si el búfer
    termina antes de completar la secuencia (conviene seguir leyendo); y
    `(_NO_LLAVE, -1)` si lo que sigue no es la forma `clave: [` (p. ej. un valor
    de cadena igual a `objects`), en cuyo caso se sigue escaneando.
    """
    n = len(buffer)
    j = desde
    while j < n and buffer[j : j + 1] in _ESPACIOS:
        j += 1
    if j >= n:
        return _INCOMPLETO, -1
    if buffer[j : j + 1] != b":":
        return _NO_LLAVE, -1
    j += 1
    while j < n and buffer[j : j + 1] in _ESPACIOS:
        j += 1
    if j >= n:
        return _INCOMPLETO, -1
    if buffer[j : j + 1] != b"[":
        return _NO_LLAVE, -1
    return _CORCHETE, j


def _es_json_valido(buffer: bytearray | bytes) -> bool:
    """Indica si el búfer contiene un documento JSON completo y bien formado.

    Materializa el búfer con `json.loads`, así que el llamador debe acotar su
    tamaño ANTES de invocarlo: aquí solo se llega con la cabecera de un cuerpo
    que se agotó sin declarar `objects` (ver `MAX_HEADER_BYTES`).
    """
    import json

    if not buffer:
        return False
    try:
        json.loads(bytes(buffer))
    except (ValueError, UnicodeDecodeError):
        return False
    return True


class _Decoder:
    """Adapta `json.JSONDecoder.raw_decode` a un búfer que crece por tramos."""

    def __init__(self) -> None:
        import json

        self._json = json
        self._decoder = json.JSONDecoder()

    def iter_objects(self, buffer: bytearray, leer: Any) -> Iterator[dict]:
        """Cede cada objeto completo de la lista hasta su `]` de cierre."""
        while True:
            self._saltar_separadores(buffer)
            if not buffer:
                if not leer():
                    raise StixStreamError("El bundle STIX terminó antes del ']'.")
                continue
            if buffer[:1] == b"]":
                return

            texto = self._texto_completo(buffer)
            if texto is not None:
                try:
                    obj, fin = self._decoder.raw_decode(texto)
                except ValueError:
                    # Puede ser un objeto AÚN INCOMPLETO (raw_decode no distingue
                    # «falta texto» de «malformado»). Se sigue leyendo; si el
                    # cuerpo se agota sin completarlo, es un error real.
                    obj = None
                    fin = 0
                else:
                    del buffer[: self._offset_bytes(buffer, fin)]
                    if isinstance(obj, dict):
                        yield obj
                    continue

            if not leer():
                raise StixStreamError("El bundle STIX contiene JSON malformado.")

    def _saltar_separadores(self, buffer: bytearray) -> None:
        """Consume espacios, comas y saltos entre objetos."""
        i = 0
        while i < len(buffer) and buffer[i : i + 1] in (b" ", b"\n", b"\r", b"\t", b","):
            i += 1
        if i:
            del buffer[:i]

    def _texto_completo(self, buffer: bytearray) -> str | None:
        """Decodifica el búfer como UTF-8; None si termina a mitad de carácter."""
        try:
            return buffer.decode("utf-8")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _offset_bytes(buffer: bytearray, chars: int) -> int:
        """Convierte un offset en CARACTERES (de raw_decode) a offset en BYTES.

        `raw_decode` trabaja sobre `str`; el búfer es `bytes`. Con UTF-8
        multibyte ambos índices divergen, así que se re-codifica el prefijo de
        caracteres ya consumidos para saber cuántos bytes ocupa.
        """
        return len(buffer.decode("utf-8")[:chars].encode("utf-8"))


__all__ = ["StixStreamError", "iter_stix_objects"]
