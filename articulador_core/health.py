"""Health checks y status de la aplicación."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .logging_config import setup_logging

# El logger por módulo (`getLogger(__name__)`) no tiene handlers: su salida nunca
# llegaba al log JSON de la aplicación y se escapaba sin formato por stderr.
logger = setup_logging()


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

    @property
    def has_errors(self) -> bool:
        """True solo si algún componente está roto.

        `is_healthy` exige que TODO esté en HEALTHY, así que una instalación
        recién estrenada (sin carpeta de config ni perfiles) ya cuenta como no
        sana. Para decidir un código de salida hace falta separar «con avisos»
        de «inservible».
        """
        return any(
            status == ComponentStatus.ERROR for status, _ in self.components.values()
        )


def _check_storage(profiles_error: Exception | None) -> tuple[ComponentStatus, str]:
    """Comprueba lectura y escritura de config sin dejar estado en el directorio."""
    import tempfile
    from pathlib import Path

    from articulador_core import storage

    try:
        if profiles_error is not None:
            raise profiles_error
        config_dir = Path(storage.CONFIG_PATH).parent
        if not config_dir.exists():
            return (
                ComponentStatus.WARNING,
                "Config directory does not exist (will create on save)",
            )
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=config_dir, delete=True, suffix=".tmp"
            ) as probe:
                probe.write("health_check_test")
                probe.flush()
            return (ComponentStatus.HEALTHY, "OK (read+write)")
        except (PermissionError, OSError):
            return (ComponentStatus.ERROR, "Config directory is read-only")
    except Exception as e:
        logger.warning("Health: storage failed - %s", e)
        return (ComponentStatus.ERROR, f"Error: {e}")


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
    # Una sola lectura de config.toml para los dos componentes: se parseaba dos veces.
    profiles: dict = {}
    profiles_error: Exception | None = None
    try:
        profiles, _active = storage.load_profiles(storage.CONFIG_PATH)
    except Exception as e:  # load_profiles es defensivo, pero no se le confía a ciegas
        profiles_error = e

    # 1. Storage - verify READ and WRITE capability (without mutating user config)
    components["storage"] = _check_storage(profiles_error)

    # 2. LLM profiles
    try:
        if profiles_error is not None:
            raise profiles_error
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
