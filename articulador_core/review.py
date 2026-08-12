from __future__ import annotations

import json

REQUIRED_FINDING_FIELDS = {"category", "severity", "original", "suggestion", "reason"}
# FIX: Validación estricta de hallazgos
ALLOWED_CATEGORIES = {"ortografía", "gramática", "semántica", "redundancia", "estructura"}
ALLOWED_SEVERITIES = {"alta", "media", "baja"}
MAX_FINDINGS = 12
MAX_FIELD_LENGTH = 500  # Máximo de caracteres por campo


def parse_findings(result: str) -> list[dict[str, str]]:
    """Extrae hallazgos válidos de la respuesta JSON del modelo con validación estricta."""
    clean = result.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        start = clean.find("{")
        if start < 0:
            return []
        payload, _end = json.JSONDecoder().raw_decode(clean[start:])
        findings = payload.get("findings", [])
    except (ValueError, AttributeError, TypeError):
        return []

    # Un `findings` que no sea lista (p. ej. una cadena enorme) se recorrería
    # carácter a carácter para descartarlo todo. Cortar antes de iterar.
    if not isinstance(findings, list):
        return []

    # FIX: Validar y limitar a 12 hallazgos
    validated = []
    for item in findings:
        # Validar estructura básica
        if not isinstance(item, dict) or not REQUIRED_FINDING_FIELDS <= item.keys():
            continue

        # Validar tipos de datos
        if not all(isinstance(item[key], str) for key in REQUIRED_FINDING_FIELDS):
            continue

        # Validar valores específicos
        category = item.get("category", "").strip().lower()
        severity = item.get("severity", "").strip().lower()
        original = item.get("original", "").strip()
        suggestion = item.get("suggestion", "").strip()
        reason = item.get("reason", "").strip()

        # Rechazar campos vacíos o valores no permitidos
        if not category or category not in ALLOWED_CATEGORIES:
            continue
        if not severity or severity not in ALLOWED_SEVERITIES:
            continue
        if not original or not suggestion or not reason:
            continue

        # Rechazar campos demasiado largos
        if any(len(field) > MAX_FIELD_LENGTH for field in [original, suggestion, reason]):
            continue

        # Construir hallazgo validado
        validated.append({
            "category": category,
            "severity": severity,
            "original": original,
            "suggestion": suggestion,
            "reason": reason
        })

        # Limitar a 12 hallazgos máximo
        if len(validated) >= MAX_FINDINGS:
            break

    return validated
