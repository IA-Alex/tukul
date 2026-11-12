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
            # sí es un error real.
            if _es_json_valido(buffer):
                return
            raise StixStreamError("El bundle STIX no contiene una lista 'objects'.")

    # Fase 2: extraer objetos uno a uno.
    yield from decoder.iter_objects(buffer, leer)


def _encontrar_inicio_lista(buffer: bytearray) -> bool:
    """Recorta el búfer hasta dejar solo lo que sigue al `[` de `"objects"`.

    Devuelve True cuando la llave y su `[` ya están en el búfer (y lo deja
    posicionado justo después). Sin la llave aún, devuelve False sin consumir.

    Cuando la llave no aparece, el búfer se conserva intacto: si el cuerpo se
    agota sin `objects`, hace falta completo para decidir si es un JSON válido
    sin objetos (→ vacío) o un cuerpo ilegible (→ error). El costo es nulo en el
    camino normal: un bundle real declara `objects` en los primeros KB, así que
    el bucle sale antes de acumular nada grande.
    """
    idx = buffer.find(MARKER)
    if idx < 0:
        return False
    corchete = buffer.find(b"[", idx + len(MARKER))
    if corchete < 0:
        return False
    del buffer[: corchete + 1]
    return True


def _es_json_valido(buffer: bytearray | bytes) -> bool:
    """Indica si el búfer contiene un documento JSON completo y bien formado."""
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
