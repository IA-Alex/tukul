"""Instantánea explícita de un artículo que acompañará al artículo activo.

Vive en su propio módulo (y no en `app.py`) para que consumidores como el
controlador de ideas o el de contexto puedan importarlo sin arrastrar la
ventana completa ni crear ciclos de importación. `app.py` lo re-exporta, así
que `from tukul_ui.app import ContextArticle` sigue funcionando.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextArticle:
    """Instantánea explícita de un artículo que acompañará al artículo activo."""

    source_id: str
    label: str
    content: str
