"""Caché de autorizaciones de contexto local.

Extraído de `TukulApp` para aislar una pieza de lógica pura (huella +
desalojo FIFO acotado) que no depende de Tk y se puede probar sin levantar
ninguna ventana.

Qué guarda: qué paquete de fragmentos locales (artículos de contexto) ya fue
aprobado para qué destino. La clave identifica destino y contenido exactos:
(endpoint, proveedor, modelo, archivos, huella del paquete), todo derivado del
workspace y no del artículo abierto — por eso sobrevive a cambiar de
documento y solo se renueva si cambia el destino o el contenido enviado.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from tukul_core.models import LlmProfile

ContextApprovalKey: TypeAlias = tuple[str, str, str, tuple[str, ...], str]


class ContextApprovalCache:
    """Conjunto ordenado de autorizaciones con desalojo FIFO real.

    Se comporta como un dict acotado para los usos habituales (`in`, `len`,
    asignación directa de clave) porque así se usaba antes de extraerlo;
    cambiar esa forma habría obligado a tocar cada llamador y cada test a la
    vez, sin ninguna ganancia real.
    """

    def __init__(self, max_size: int = 128) -> None:
        self._max_size = max_size
        self._approved: dict[ContextApprovalKey, None] = {}

    def __contains__(self, key: object) -> bool:
        return key in self._approved

    def __len__(self) -> int:
        return len(self._approved)

    def __setitem__(self, key: ContextApprovalKey, value: None) -> None:
        self.remember(key)

    @staticmethod
    def key_for(profile: LlmProfile, packet: str, files: list[str]) -> ContextApprovalKey:
        """Identifica contenido y destinatario exactos de una autorización."""
        content_hash = hashlib.sha256(packet.encode("utf-8")).hexdigest()[:16]
        return (profile.endpoint, profile.provider, profile.model, tuple(files), content_hash)

    def remember(self, key: ContextApprovalKey) -> None:
        """Guarda una autorización ya calculada respetando el tope FIFO."""
        if key in self._approved:
            self._approved.pop(key)
        while len(self._approved) >= self._max_size:
            self._approved.pop(next(iter(self._approved)), None)
        self._approved[key] = None

    def remember_for(self, profile: LlmProfile, packet: str, files: list[str]) -> None:
        """Registra una autorización de sesión sin pasar por `key_for` en el llamador."""
        if not files:
            return
        self.remember(self.key_for(profile, packet, files))
