"""Health checks y status de la aplicación."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .logging_config import file_logging_status, setup_logging

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
    # Ruta realmente inspeccionada. Un diagnóstico que no dice sobre QUÉ archivo
    # informa puede mentir sin que se note.
    config_path: str = ""

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


def _check_storage(profiles_error: Exception | None, config_path: Path) -> tuple[ComponentStatus, str]:
    """Comprueba lectura y escritura de config sin dejar estado en el directorio."""
    import tempfile

    try:
        if profiles_error is not None:
            raise profiles_error
        config_dir = config_path.parent
        if not config_dir.exists():
            return (
                ComponentStatus.WARNING,
                "La carpeta de config no existe (se creará al guardar)",
            )
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=config_dir, delete=True, suffix=".tmp"
            ) as probe:
                probe.write("health_check_test")
                probe.flush()
            return (ComponentStatus.HEALTHY, "OK (lectura+escritura)")
        except (PermissionError, OSError):
            return (ComponentStatus.ERROR, "La carpeta de config es de solo lectura")
    except Exception as e:
        logger.warning("Health: fallo de almacenamiento - %s", e)
        return (ComponentStatus.ERROR, f"Error: {e}")


def check_health(config_path: Path | str | None = None) -> HealthStatus:
    """Verifica salud de la aplicación.

    Componentes:
    - storage: ¿Se puede leer/escribir config?
    - llm: ¿Hay al menos un perfil habilitado?
    - logging: ¿Funciona logging?

    Args:
        config_path: Archivo de perfiles a inspeccionar. Por defecto,
            storage.CONFIG_PATH. Sin este parámetro, `--config` quedaba mudo:
            el diagnóstico informaba siempre del config por defecto aunque la
            CLI apuntara a otro, y la respuesta parecía válida.

    Returns:
        HealthStatus con detalle de cada componente
    """
    from datetime import datetime

    from tukul_core import storage

    resolved = Path(config_path) if config_path is not None else storage.CONFIG_PATH
    components = {}
    timestamp = datetime.now().isoformat()
    # Una sola lectura de config.toml para los dos componentes: se parseaba dos veces.
    profiles: dict = {}
    profiles_error: Exception | None = None
    try:
        profiles, _active = storage.load_profiles(resolved)
    except Exception as e:  # load_profiles es defensivo, pero no se le confía a ciegas
        profiles_error = e

    # 1. Storage - verify READ and WRITE capability (without mutating user config)
    components["storage"] = _check_storage(profiles_error, resolved)

    # 2. LLM profiles
    try:
        if profiles_error is not None:
            raise profiles_error
        enabled_count = sum(1 for p in profiles.values() if p.enabled)
        if enabled_count > 0:
            components["llm"] = (
                ComponentStatus.HEALTHY,
                f"{enabled_count} perfil(es) habilitado(s)",
            )
        else:
            components["llm"] = (ComponentStatus.WARNING, "Sin perfiles habilitados")
        # Campos descartados por tipo: el perfil arranca con los valores por
        # defecto y el usuario no tenía forma de saber por qué. Va dentro del
        # componente `llm` en vez de como componente propio: la clave "config"
        # ya la usan los usuarios de `status.components` para el archivo.
        descartados = list(storage.DISCARDED_PROFILE_FIELDS)
        if descartados:
            muestra = "; ".join(descartados[:3])
            resto = f" (+{len(descartados) - 3} más)" if len(descartados) > 3 else ""
            estado_llm, detalle = components["llm"]
            components["llm"] = (
                ComponentStatus.WARNING if estado_llm.is_ok() else estado_llm,
                f"{detalle} · {len(descartados)} campo(s) ignorado(s) por tipo: "
                f"{muestra}{resto}",
            )
    except Exception as e:
        components["llm"] = (ComponentStatus.ERROR, f"Error: {e}")
        logger.warning(f"Health: fallo del LLM - {e}")

    # 3. Logging - estado REAL del destino, no "logger.debug() no lanzó".
    # Con handler de consola presente, debug() nunca lanza: el componente se
    # declaraba sano incluso con el archivo de log inexistente por sistema de
    # archivos de solo lectura.
    try:
        operativo, detalle = file_logging_status()
        # Aviso, no error: la aplicación funciona sin archivo de log; lo que se
        # pierde es la capacidad de diagnosticar después.
        components["logging"] = (
            (ComponentStatus.HEALTHY, detalle) if operativo
            else (ComponentStatus.WARNING, detalle)
        )
    except Exception as e:
        components["logging"] = (ComponentStatus.ERROR, f"Error: {e}")

    # Determinar salud general
    is_healthy = all(status.is_ok() for status, _ in components.values())

    status = HealthStatus(
        is_healthy=is_healthy,
        components=components,
        timestamp=timestamp,
        config_path=str(resolved),
    )

    # Log resultado
    formatted_components = {comp: msg for comp, (_, msg) in components.items()}
    if is_healthy:
        logger.info(f"Health check superado: {formatted_components}")
    else:
        logger.warning(f"Health check con avisos: {formatted_components}")

    return status


def status_string(status: HealthStatus | None = None) -> str:
    """Retorna estado de salud como string legible.

    Args:
        status: HealthStatus pre-computado. Si es None, se ejecuta check_health()
    """
    if status is None:
        status = check_health()
    lines = [f"Salud: {'OK' if status.is_healthy else 'ISSUES'} ({status.timestamp})"]
    if status.config_path:
        # Decir qué archivo se inspeccionó es lo que hace auditable el resultado.
        lines.append(f"  config: {status.config_path}")
    for comp, (comp_status, message) in status.components.items():
        lines.append(f"  {comp}: {comp_status.value} {message}")
    return "\n".join(lines)
