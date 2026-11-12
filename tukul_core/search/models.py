"""Modelos de búsqueda externa.

Los resultados se conservan como metadatos de descubrimiento, no como artículos
completos. El contenido externo nunca se convierte automáticamente en contexto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class SearchQuery:
    """Consulta explícita solicitada por el usuario."""

    text: str
    days: int = 30
    language: str | None = None
    max_results: int = 20

    def __post_init__(self) -> None:
        text = self.text.strip()
        if not text:
            raise ValueError("La consulta de búsqueda no puede estar vacía.")
        if not 1 <= self.days <= 365:
            raise ValueError("La ventana de búsqueda debe estar entre 1 y 365 días.")
        if not 1 <= self.max_results <= 100:
            raise ValueError("El número de resultados debe estar entre 1 y 100.")
        object.__setattr__(self, "text", text)


@dataclass(frozen=True)
class SearchResult:
    """Resultado mínimo y trazable de una fuente de descubrimiento."""

    result_id: str
    provider: str
    title: str
    snippet: str
    url: str
    domain: str
    published: datetime | None = None
    language: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise ValueError("Los resultados externos deben usar HTTPS.")
        if not self.title.strip() or not self.url.strip():
            raise ValueError("Un resultado necesita título y URL.")

    @property
    def observed_at(self) -> datetime:
        """Momento estable para mostrar la antigüedad si no hay fecha publicada."""
        return self.published or datetime.now(UTC)
