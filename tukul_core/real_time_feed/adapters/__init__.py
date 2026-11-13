"""Adaptadores para cada fuente oficial.

Cada adaptador implementa `SourceAdapter` y se registra en el diccionario
`REGISTRY` para que `FeedOrchestrator` los descubra por ID.
"""

from __future__ import annotations

from .arxiv import ArxivAdapter
from .base import SourceAdapter
from .epss import EpssAdapter
from .huggingface_papers import HuggingFacePapersAdapter
from .kev import KevAdapter
from .mitre_attack import MitreAttackAdapter
from .nvd import NvdAdapter
from .openalex import OpenAlexAdapter

REGISTRY: dict[str, type[SourceAdapter]] = {
    "nvd": NvdAdapter,
    "epss": EpssAdapter,
    "kev": KevAdapter,
    "mitre-attack": MitreAttackAdapter,
    "arxiv": ArxivAdapter,
    "huggingface-papers": HuggingFacePapersAdapter,
    "openalex": OpenAlexAdapter,
}

__all__ = [
    "REGISTRY",
    "ArxivAdapter",
    "EpssAdapter",
    "HuggingFacePapersAdapter",
    "KevAdapter",
    "MitreAttackAdapter",
    "NvdAdapter",
    "OpenAlexAdapter",
    "SourceAdapter",
]
