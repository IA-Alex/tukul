from __future__ import annotations

import json


REQUIRED_FINDING_FIELDS = {"category", "severity", "original", "suggestion", "reason"}


def parse_findings(result: str) -> list[dict[str, str]]:
    """Extrae hallazgos válidos de la respuesta JSON del modelo."""
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
    return [item for item in findings if isinstance(item, dict) and REQUIRED_FINDING_FIELDS <= item.keys() and all(isinstance(item[key], str) for key in REQUIRED_FINDING_FIELDS)]
