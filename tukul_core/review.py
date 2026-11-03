from __future__ import annotations

import json

REQUIRED_FINDING_FIELDS = {"category", "severity", "original", "suggestion", "reason"}
# FIX: Validación estricta de hallazgos
ALLOWED_CATEGORIES = {"ortografía", "gramática", "semántica", "redundancia", "estructura"}
ALLOWED_SEVERITIES = {"alta", "media", "baja"}
MAX_FINDINGS = 12
MAX_FIELD_LENGTH = 500  # Máximo de caracteres por campo
# Tope de entrada antes de `raw_decode`: el tope de hallazgos se aplica DESPUÉS
# de materializar el árbol, así que un JSON enorme (o malformado desde el
# principio) se parseaba entero antes de poder descartarlo. 12 hallazgos de
# 5*500 caracteres caben holgadamente en este margen.
MAX_RESULT_CHARS = 512 * 1024


def _validated_finding(item: object) -> dict[str, str] | None:
    """Normaliza un hallazgo crudo, o None si incumple alguna regla."""
    if not isinstance(item, dict) or not REQUIRED_FINDING_FIELDS <= item.keys():
        return None
    if not all(isinstance(item[key], str) for key in REQUIRED_FINDING_FIELDS):
        return None

    category = item["category"].strip().lower()
    severity = item["severity"].strip().lower()
    original = item["original"].strip()
    suggestion = item["suggestion"].strip()
    reason = item["reason"].strip()

    if category not in ALLOWED_CATEGORIES or severity not in ALLOWED_SEVERITIES:
        return None
    if not original or not suggestion or not reason:
        return None
    if any(len(field) > MAX_FIELD_LENGTH for field in (original, suggestion, reason)):
        return None
    return {
        "category": category,
        "severity": severity,
        "original": original,
        "suggestion": suggestion,
        "reason": reason,
    }


def parse_findings(result: str) -> list[dict[str, str]]:
    """Extrae hallazgos válidos de la respuesta JSON del modelo con validación estricta."""
    clean = result.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # Envolver el bloque externo de un JSON encapsulado puede rebasar el tope
    # sin que el contenido útil lo haga: se recorta antes de decodificar.
    if len(clean) > MAX_RESULT_CHARS:
        return []
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

    validated: list[dict[str, str]] = []
    for item in findings:
        finding = _validated_finding(item)
        if finding is None:
            continue
        validated.append(finding)
        if len(validated) >= MAX_FINDINGS:
            break

    return validated
