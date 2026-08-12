"""Validación y auditoría de configuración en startup."""
from __future__ import annotations

from articulador_core.logging_config import setup_logging
from articulador_core.models import LlmProfile

# Mismo motivo que en health.py: sin esto los avisos de arranque no llegaban
# al log JSON de la aplicación.
logger = setup_logging()


def _profile_warnings(profile: LlmProfile, name: str) -> list[str]:
    """Avisos sobre campos vacíos y límites de tokens inusuales de un perfil."""
    warnings = []
    if not profile.enabled:
        warnings.append(f"Perfil '{name}' está DESHABILITADO (provider={profile.provider})")
    for field, etiqueta in (("endpoint", "endpoint"), ("model", "model"), ("api_key_env", "api_key_env")):
        if not getattr(profile, field):
            warnings.append(f"Perfil '{name}': {etiqueta} vacío")
    if profile.max_output_tokens < 100:
        warnings.append(f"Perfil: max_output_tokens muy bajo ({profile.max_output_tokens})")
    if profile.max_output_tokens > 10000:
        warnings.append(f"Perfil: max_output_tokens muy alto ({profile.max_output_tokens})")
    if profile.max_total_model_tokens < profile.max_output_tokens * 2:
        warnings.append("Perfil: max_total_model_tokens apenas mayor que max_output_tokens")
    return warnings


def validate_startup_config(profiles: dict[str, LlmProfile], active_profile: str) -> tuple[bool, list[str]]:
    """Valida configuración de LLM en startup.

    Returns:
        (is_valid, warnings): Bool si válida, lista de warnings

    Warnings generados:
    - Perfil no encontrado
    - Perfil deshabilitado
    - Campo vacío (model, endpoint, etc)
    - Límite de tokens inusual
    - Perfil activo no existe
    """
    warnings = []

    # Validar que existe perfil activo
    if active_profile not in profiles:
        warnings.append(f"Perfil activo '{active_profile}' no existe en configuración")
        if profiles:
            first_key = next(iter(profiles))
            warnings.append(f"   Se usará primer perfil: '{first_key}'")
        return False, warnings

    profile = profiles[active_profile]
    warnings.extend(_profile_warnings(profile, active_profile))

    is_valid = len(warnings) == 0

    if is_valid:
        logger.info(f"✓ Configuración válida: perfil '{active_profile}' habilitado")
    else:
        logger.warning(f"Configuración con warnings ({len(warnings)})")
        for w in warnings:
            logger.warning(w)

    return is_valid, warnings
