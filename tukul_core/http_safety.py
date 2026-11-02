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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Nunca sigue redirecciones HTTP(S)."""

    def redirect_request(self, *args, **kwargs):
        """Rechaza el seguimiento: devuelve None para que el 3xx llegue como error."""
        return None


# Sustituye el HTTPRedirectHandler por defecto de urlopen; el resto de handlers
# (proxy, HTTPS, etc.) se conservan vía build_opener().
NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())
