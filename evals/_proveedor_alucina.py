#!/usr/bin/env python3
"""Proveedor DOBLE para el control negativo del eval funcional.

Simula a un modelo que INVENTA hallazgos sobre un texto limpio: el fallo que
`hallazgos_usables.js` con `maximo: 0` debe detectar. Determinista y sin red,
así que sirve como prueba de la aserción en ambos sentidos:

- con `maximo` aplicado, el eval debe marcar este caso en ROJO;
- si sale en verde, la aserción no está midiendo alucinaciones.
"""

from __future__ import annotations

import json
import sys

INVENTADOS = {
    "findings": [
        {
            "category": "ortografía",
            "severity": "alta",
            "original": "ciberseguridad",
            "suggestion": "seguridad informática",
            "reason": "Término considerado incorrecto por el revisor.",
        },
        {
            "category": "estructura",
            "severity": "media",
            "original": "documentar los cambios",
            "suggestion": "registrar las modificaciones",
            "reason": "Se sugiere un cambio sin fundamento en el texto.",
        },
    ]
}


def main() -> int:
    """Devuelve siempre la misma respuesta inventada, en formato promptfoo."""
    print(json.dumps({
        "output": json.dumps(INVENTADOS, ensure_ascii=False),
        "metadata": {"doble": "alucina", "parse_findings_count": 2},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
