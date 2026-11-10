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

import urllib.request
import xml.etree.ElementTree  # nosec B405 - uso endurecido: solo vía xml_fromstring_seguro
from typing import Any


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Nunca sigue redirecciones HTTP(S)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Rechaza el seguimiento: devuelve None para que el 3xx llegue como error."""
        return None


# Sustituye el HTTPRedirectHandler por defecto de urlopen; el resto de handlers
# (proxy, HTTPS, etc.) se conservan vía build_opener().
NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


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
