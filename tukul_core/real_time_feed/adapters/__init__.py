"""Adaptadores para cada fuente oficial.

Cada adaptador implementa `SourceAdapter` y se registra en el diccionario
`REGISTRY` para que `FeedOrchestrator` los descubra por ID.
"""

from __future__ import annotations

from .base import SourceAdapter
from .nvd import NvdAdapter
from .epss import EpssAdapter
from .kev import KevAdapter
from .mitre_attack import MitreAttackAdapter
from .arxiv import ArxivAdapter

REGISTRY: dict[str, type[SourceAdapter]] = {
    "nvd": NvdAdapter,
    "epss": EpssAdapter,
    "kev": KevAdapter,
    "mitre-attack": MitreAttackAdapter,
    "arxiv": ArxivAdapter,
}

__all__ = [
    "SourceAdapter",
    "NvdAdapter",
    "EpssAdapter",
    "KevAdapter",
    "MitreAttackAdapter",
    "ArxivAdapter",
    "REGISTRY",
]
