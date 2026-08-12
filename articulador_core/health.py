"""Health checks y status de la aplicación."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ComponentStatus(Enum):
    """Status de cada componente de salud."""

    HEALTHY = "✓"
    WARNING = "⚠️ "
    ERROR = "✗"

    def is_ok(self) -> bool:
        """True si el componente está sano."""
        return self == ComponentStatus.HEALTHY


@dataclass
class HealthStatus:
    """Estado de salud de la aplicación."""

    is_healthy: bool  # True si todo OK
    components: dict[str, tuple[ComponentStatus, str]]  # "component": (status, message)
    timestamp: str  # ISO format


def check_health() -> HealthStatus:
    """Verifica salud de la aplicación.

    Componentes:
    - storage: ¿Se puede leer/escribir config?
    - llm: ¿Hay al menos un perfil habilitado?
    - logging: ¿Funciona logging?

    Returns:
        HealthStatus con detalle de cada componente
    """
    from datetime import datetime

    from articulador_core import storage

    components = {}
    timestamp = datetime.now().isoformat()

    # 1. Storage - verify READ and WRITE capability (without mutating user config)
    try:
        import tempfile
        from pathlib import Path

        config_path = storage.CONFIG_PATH
        profiles, _ = storage.load_profiles(config_path)

        # Verify WRITE capability WITHOUT creating state
        config_dir = Path(config_path).parent
        if not config_dir.exists():
            components["storage"] = (
                ComponentStatus.WARNING,
                "Config directory does not exist (will create on save)",
            )
        else:
            try:
                # Test write en directorio existente usando tempfile
                with tempfile.NamedTemporaryFile(
                    mode="w", dir=config_dir, delete=True, suffix=".tmp"
                ) as f:
                    f.write("health_check_test")
                    f.flush()
                components["storage"] = (ComponentStatus.HEALTHY, "OK (read+write)")
            except (PermissionError, OSError):
                # Directorio existe pero no es escribible
                components["storage"] = (
                    ComponentStatus.ERROR,
                    "Config directory is read-only",
                )
    except Exception as e:
        components["storage"] = (ComponentStatus.ERROR, f"Error: {e}")
        logger.warning(f"Health: storage failed - {e}")

    # 2. LLM profiles
    try:
        profiles, _ = storage.load_profiles(storage.CONFIG_PATH)
        enabled_count = sum(1 for p in profiles.values() if p.enabled)
        if enabled_count > 0:
            components["llm"] = (
                ComponentStatus.HEALTHY,
                f"{enabled_count} profile(s) enabled",
            )
        else:
            components["llm"] = (ComponentStatus.WARNING, "No profiles enabled")
    except Exception as e:
        components["llm"] = (ComponentStatus.ERROR, f"Error: {e}")
        logger.warning(f"Health: llm failed - {e}")

    # 3. Logging
    try:
        logger.debug("Health check: logging test")
        components["logging"] = (ComponentStatus.HEALTHY, "OK")
    except Exception as e:
        components["logging"] = (ComponentStatus.ERROR, f"Error: {e}")

    # Determinar salud general
    is_healthy = all(status.is_ok() for status, _ in components.values())

    status = HealthStatus(
        is_healthy=is_healthy, components=components, timestamp=timestamp
    )

    # Log resultado
    formatted_components = {comp: msg for comp, (_, msg) in components.items()}
    if is_healthy:
        logger.info(f"Health check passed: {formatted_components}")
    else:
        logger.warning(f"Health check issues: {formatted_components}")

    return status


def status_string(status: HealthStatus | None = None) -> str:
    """Retorna estado de salud como string legible.

    Args:
        status: HealthStatus pre-computado. Si es None, se ejecuta check_health()
    """
    if status is None:
        status = check_health()
    lines = [f"Salud: {'OK' if status.is_healthy else 'ISSUES'} ({status.timestamp})"]
    for comp, (comp_status, message) in status.components.items():
        lines.append(f"  {comp}: {comp_status.value} {message}")
    return "\n".join(lines)
