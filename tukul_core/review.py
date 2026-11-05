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


def _decode_payload(result: str) -> tuple[str, object | None]:
    """Localiza y decodifica el objeto JSON; devuelve la causa si no se puede."""
    clean = result.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if len(clean) > MAX_RESULT_CHARS:
        return "truncado", None
    start = clean.find("{")
    if start < 0:
        return "sin_json", None
    try:
        payload, _end = json.JSONDecoder().raw_decode(clean[start:])
    except ValueError:
        # Hay una llave de apertura pero no un objeto completo: corte o
        # respuesta a medias, que es información distinta de una prosa.
        return "truncado", None
    return "ok", payload


def diagnose_findings(result: str) -> tuple[str, list[dict[str, str]]]:
    """Devuelve la causa del resultado junto a los hallazgos válidos.

    `parse_findings` colapsa cuatro situaciones distintas en `[]`: respuesta sin
    JSON, JSON con otro esquema (p. ej. `{"respuesta": …}`), artículo sin
    hallazgos y JSON truncado. La interfaz las presentaba todas como «el modelo
    no devolvió una revisión utilizable», cuando una de ellas —el artículo sin
    hallazgos— es un éxito. La causa se separa aquí, en el único punto que
    conoce el formato, en vez de reparsear en la UI.

    Causas: ``ok``, ``sin_hallazgos``, ``sin_json``, ``esquema_ajeno``,
    ``truncado``.
    """
    causa, payload = _decode_payload(result)
    if causa != "ok":
        return causa, []
    if not isinstance(payload, dict) or "findings" not in payload:
        return "esquema_ajeno", []
    findings = payload["findings"]
    if not isinstance(findings, list):
        return "esquema_ajeno", []

    validated: list[dict[str, str]] = []
    for item in findings:
        finding = _validated_finding(item)
        if finding is None:
            continue
        validated.append(finding)
        if len(validated) >= MAX_FINDINGS:
            break

    if not validated:
        # Lista presente y vacía, o hallazgos todos descartados por el
        # validador. Sin ninguno útil, el artículo se considera sin hallazgos.
        return "sin_hallazgos", []
    return "ok", validated


def parse_findings(result: str) -> list[dict[str, str]]:
    """Extrae hallazgos válidos de la respuesta JSON del modelo con validación estricta."""
    return diagnose_findings(result)[1]
