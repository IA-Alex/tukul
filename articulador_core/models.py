from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LlmProfile:
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
        return self.provider != "disabled" and bool(self.endpoint and self.model)


@dataclass
class ChatMessage:
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
    document_path: Path | None = None
    project_path: Path | None = None
    article: str = ""
    corpus_path: Path | None = None
    evidence: list[str] = field(default_factory=list)
    conversation: list[ChatMessage] = field(default_factory=list)
    dirty: bool = False
    # request_active se mantiene solo como conveniencia, se sincroniza con RequestState
    request_active: bool = False
