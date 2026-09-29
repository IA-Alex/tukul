from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class LlmProfile:
    """Perfil LLM: proveedor, endpoint, modelo, límites de tokens y precios."""

    name: str = "default"
    provider: str = "disabled"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    max_output_tokens: int = 1000
    max_context_chars: int = 48_000
    max_total_model_tokens: int = 128_000  # Límite TOTAL entrada + salida
    temperature: float = 0.5
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("La temperatura debe estar entre 0.0 y 2.0.")
        if self.max_output_tokens < 1 or self.max_output_tokens > 16_000:
            raise ValueError("El máximo de tokens de salida debe estar entre 1 y 16000.")
        if self.max_context_chars < 100:
            raise ValueError("El máximo de contexto debe ser de al menos 100 caracteres.")
        if self.max_total_model_tokens < self.max_output_tokens:
            raise ValueError(
                f"max_total_model_tokens ({self.max_total_model_tokens}) "
                f"debe ser >= max_output_tokens ({self.max_output_tokens})"
            )
        if self.input_price_per_million < 0 or self.output_price_per_million < 0:
            raise ValueError("Los precios por millón de tokens no pueden ser negativos.")

    @property
    def enabled(self) -> bool:
        """True si el perfil está habilitado y tiene endpoint y modelo."""
        return self.provider != "disabled" and bool(self.endpoint and self.model)


@dataclass
class ChatMessage:
    """Mensaje de conversación con validación de rol y contenido en runtime."""

    role: str
    content: str

    def __post_init__(self):
        """Valida tipos y valores permitidos en runtime."""
        # Validar que role y content sean strings
        if not isinstance(self.role, str):
            raise TypeError(f"role debe ser str, se recibió {type(self.role).__name__}")
        if not isinstance(self.content, str):
            raise TypeError(f"content debe ser str, se recibió {type(self.content).__name__}")

        # Validar que role es uno de los permitidos
        allowed_roles = {"user", "assistant"}
        if self.role not in allowed_roles:
            raise ValueError(f"role debe ser uno de {allowed_roles}, se recibió '{self.role}'")


@dataclass
class ArticleSession:
    """Sesión de trabajo sobre un documento: artículo activo y su conversación."""

    document_path: Path | None = None
    project_path: Path | None = None
    article: str = ""
    conversation: list[ChatMessage] = field(default_factory=list)
    dirty: bool = False
    # request_active se mantiene solo como conveniencia, se sincroniza con RequestState
    request_active: bool = False


# ─── Nuevos tipos: Feed de fuentes oficiales y sugerencias de impacto ────────

@dataclass(frozen=True)
class FeedSource:
    """Identificador de una fuente oficial consultable.

    Cada fuente tiene un ID corto, una etiqueta legible, un tipo (CVE,
    TTP, paper, reporte, guía, alerta), la URL base, si requiere API key,
    y el intervalo mínimo respetuoso entre consultas.
    """

    id: str
    label: str
    type: str  # "cve" | "ttp" | "paper" | "report" | "guideline" | "alert"
    base_url: str
    requires_api_key: bool
    refresh_interval_minutes: int


@dataclass(frozen=True)
class FeedEntry:
    """Entrada normalizada proveniente de cualquier fuente oficial.

    Contiene el texto, metadatos de publicación, nivel de severidad
    normalizado (0-10), nivel de confianza según la reputación de la
    fuente, referencias originales y etiquetas computadas.
    """

    source_id: str  # "nvd:CVE-2026-12345"
    source: str  # "nvd"
    title: str
    description: str
    url: str
    published: datetime
    updated: datetime | None = None
    topics: tuple[str, ...] = ()
    severity: float | None = None  # CVSS 0-10 o normalizado
    confidence: float = 1.0  # 0.0-1.0
    raw_references: tuple[str, ...] = ()
    tags: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class FoggAnalysis:
    """Análisis según Fogg Behavior Model aplicado a una sugerencia.

    Modela tres ejes:
    - motivation: factores que impulsan la acción (urgencia, relevancia).
    - ability: qué tan factible es actuar (facilidad de implementación).
    - triggers: desencadenantes concretos (parche disponible, alerta activa).
    """

    motivation: dict[str, float]
    ability: dict[str, float]
    triggers: tuple[str, ...]
    summary: str = ""


@dataclass(frozen=True)
class SourceConflict:
    """Contradicción o discrepancia detectada entre fuentes oficiales.

    Se reporta al usuario para que decida cómo interpretarla, no se oculta.
    """

    sources: tuple[str, ...]  # ("nvd", "mitre-attack")
    field: str  # "severity" | "remediation" | "impact"
    description: str
    severity: str = "warning"  # "info" | "warning" | "contradiction"


@dataclass(frozen=True)
class ConsumerSuggestion:
    """Sugerencia de impacto generada a partir de entradas de fuentes oficiales.

    Incluye la fundamentación (qué entradas la respaldan), el análisis Fogg,
    el nivel de incertidumbre, las contradicciones detectadas y un disclaimer.
    No contiene frases de validación vacía ("buena idea", "esto es correcto").
    """

    id: str
    source_entries: tuple[str, ...]
    title: str
    rationale: str
    fogg: FoggAnalysis
    suggested_article_focus: str
    target_audience: str  # "directivos" | "tecnicos" | "publico general"
    impact_level: str  # "bajo" | "medio" | "alto"
    uncertainty: str
    conflicts: tuple[SourceConflict, ...] = ()
    disclaimer: str = (
        "Basado en fuentes oficiales. Revisa y contrasta antes de usar. "
        "Esta sugerencia no constituye consejo profesional de seguridad."
    )
    generated_at: datetime = field(default_factory=lambda: datetime.now())
