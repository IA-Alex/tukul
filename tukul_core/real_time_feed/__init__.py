"""Consulta en tiempo real a fuentes oficiales de ciberseguridad e IA.

Este paquete extiende el patrón de `threat_feed.py` a más fuentes oficiales
(NVD, MITRE ATT&CK, arXiv, NIST, ENISA, OWASP, NCSC) y añade un pipeline de
análisis cualitativo (Fogg Behavior Model, detección de contradicciones,
generación de sugerencias de impacto) sin caer en amarillismo, psicofancia
ni validaciones vacías.

Estructura:
- `adapters/`: cada fuente oficial implementa `SourceAdapter` (ABC).
- `orchestrator.py`: `FeedOrchestrator` coordina fetch paralelo.
- `cache.py`: `FeedCache` con TTL y escritura atómica.
- `normalizer.py`: unifica formatos dispares a `FeedEntry`.
"""

from __future__ import annotations

from .cache import FeedCache
from .normalizer import FeedNormalizer
from .orchestrator import FeedOrchestrator

__all__ = [
    "FeedCache",
    "FeedNormalizer",
    "FeedOrchestrator",
]
