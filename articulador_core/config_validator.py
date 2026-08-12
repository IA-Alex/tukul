"""Validación y auditoría de configuración en startup."""
from __future__ import annotations

import logging

from articulador_core.models import LlmProfile

logger = logging.getLogger(__name__)


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
        warnings.append(f"⚠️  Perfil activo '{active_profile}' no existe en configuración")
        if profiles:
            first_key = next(iter(profiles))
            warnings.append(f"   Se usará primer perfil: '{first_key}'")
        return False, warnings

    profile = profiles[active_profile]

    # Validar que está habilitado
    if not profile.enabled:
        warnings.append(f"⚠️  Perfil '{active_profile}' está DESHABILITADO (provider={profile.provider})")

    # Validar campos críticos
    if not profile.endpoint:
        warnings.append(f"⚠️  Perfil '{active_profile}': endpoint vacío")

    if not profile.model:
        warnings.append(f"⚠️  Perfil '{active_profile}': model vacío")

    if not profile.api_key_env:
        warnings.append(f"⚠️  Perfil '{active_profile}': api_key_env vacío")

    # Validar límites de tokens (valores inusuales)
    if profile.max_output_tokens < 100:
        warnings.append(f"⚠️  Perfil: max_output_tokens muy bajo ({profile.max_output_tokens})")

    if profile.max_output_tokens > 10000:
        warnings.append(f"⚠️  Perfil: max_output_tokens muy alto ({profile.max_output_tokens})")

    if profile.max_total_model_tokens < profile.max_output_tokens * 2:
        warnings.append("⚠️  Perfil: max_total_model_tokens apenas mayor que max_output_tokens")

    is_valid = len(warnings) == 0

    if is_valid:
        logger.info(f"✓ Configuración válida: perfil '{active_profile}' habilitado")
    else:
        logger.warning(f"⚠️  Configuración con warnings ({len(warnings)})")
        for w in warnings:
            logger.warning(w)

    return is_valid, warnings
