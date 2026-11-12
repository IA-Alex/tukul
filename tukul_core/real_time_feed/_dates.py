"""Normalización de fechas de las fuentes del feed a un único contrato.

Las cinco fuentes oficiales publican fechas ISO 8601 con variantes que antes se
manejaban con cuatro implementaciones casi idénticas:

- NVD: `2026-11-11T22:17:10.820` — **sin** sufijo de zona.
- CISA KEV: `2026-11-10` — solo fecha, sin zona.
- arXiv / MITRE: `2026-11-04T10:00:00Z` — con `Z`.

La duplicación ya causó dos incidentes reales: un `datetime` NAIVE comparado
contra un `since` aware en `FeedNormalizer.normalize_all` tumbaba el pipeline de
ideas (`TypeError: can't compare offset-naive and offset-aware datetimes`), y
cada adaptador tenía que arreglarlo por su cuenta. Este módulo es la única
fuente de verdad: toda fecha del feed sale con zona horaria (UTC cuando la
fuente no la declara, que es el caso de NVD y KEV).
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["parse_feed_date"]


def parse_feed_date(raw: str, default: datetime | None = None) -> datetime:
    """Parsea una fecha ISO 8601 del feed garantizando un `datetime` con zona.

    Acepta las tres variantes observadas (`Z`, offset explícito y sin sufijo de
    zona). Cuando la fecha no trae offset se asume UTC — es lo que publican NVD
    y CISA KEV, y lo que `FeedNormalizer.normalize_all` espera al comparar.

    Args:
        raw: Cadena ISO 8601 de la fuente. Un tipo no textual provoca el mismo
            `AttributeError` que produciría `str.replace` (contrato heredado de
            `_parse_stix_date`: la validación de tipo no es responsabilidad de
            este ayudante).
        default: Valor devuelto si la cadena no es una fecha válida. Si es
            `None` y la fecha no se puede parsear, se lanza `ValueError`.

    Returns:
        Un `datetime` con zona horaria (UTC si la fuente no la declaraba).
    """
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        if default is not None:
            return default
        raise
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
