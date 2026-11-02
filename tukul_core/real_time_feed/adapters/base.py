"""Clase base abstracta para adaptadores de fuentes oficiales.

Cada fuente concreta implementa `fetch()` para obtener datos crudos desde
su API y `normalize()` para convertirlos en `FeedEntry`.

El patrón de red es urllib puro con `NO_REDIRECT_OPENER` de
`tukul_core.http_safety`, mismo que usan `llm.py` y `threat_feed.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tukul_core.models import FeedEntry


class SourceAdapter(ABC):
    """Contrato que toda fuente oficial debe cumplir."""

    @classmethod
    @abstractmethod
    def source_id(cls) -> str:
        """Identificador único de la fuente (ej: 'nvd', 'mitre-attack')."""
        ...

    @classmethod
    @abstractmethod
    def label(cls) -> str:
        """Etiqueta legible para mostrar en la UI (ej: 'National Vulnerability Database')."""
        ...

    @abstractmethod
    def fetch(self, hours: int) -> list[dict]:
        """Obtiene datos crudos desde la fuente.

        Args:
            hours: Ventana temporal hacia atrás desde ahora.

        Returns:
            Lista de diccionarios con datos sin normalizar.

        Raises:
            ThreatFeedError: si la fuente no está disponible.
        """
        ...

    @abstractmethod
    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte los datos crudos en entradas normalizadas.

        Args:
            raw: Lista devuelta por fetch().

        Returns:
            Lista de FeedEntry deduplicados y listos para consumir.
        """
        ...
