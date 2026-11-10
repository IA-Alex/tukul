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


# Señales de que la respuesta deja de ser una revisión y pasa a ser la
# respuesta del atacante: una instrucción embebida en el artículo logró
# cambiar el rol del modelo. Se buscan como texto PROPIO del modelo (prosa
# libre o prosa dentro de un JSON sin el contrato de hallazgos), nunca como
# cita: la regla del proyecto es que citar el ataque para señalarlo NO es
# obedecerlo. El SYSTEM_PROMPT ya ordena resistir; esto es la red de seguridad
# del lado de la aplicación, que no depende de que el modelo obedezca.
_ROLE_BREAK_SIGNALS = (
    "sin restricciones",
    "sin filtros",
    "modo desarrollador",
    "he sido desbloqueado",
    "acceso concedido",
    "jaqueado",
    "pwned",
    "a partir de ahora soy",
    "mi nuevo rol",
    "soy el sistema",
)
# Fragmentos distintivos del propio SYSTEM_PROMPT. Si aparecen, el modelo lo
# reprodujo: es fuga de las instrucciones internas, no una revisión.
_SYSTEM_PROMPT_LEAK_SIGNALS = (
    "eres tukul, un editor conversacional",
    "datos no confiables",
    "activen herramientas",
    "autoridad de sistema",
    "no inventes hechos ni modifiques archivos",
)
# Una negativa legítima del modelo también es texto en prosa y puede mencionar
# el ataque (p. ej. «contiene instrucciones dirigidas al sistema»). Se acepta
# como conducta correcta y no se marca como obediencia.
_LEGITIMATE_REFUSAL = (
    "no puedo procesar",
    "no puedo revisar",
    "no puedo seguir",
    "no puedo continuar",
    "no puedo analizar",
    "no debo procesar",
    "no debo revisar",
    "no debo seguir",
    "instrucciones ocultas",
    "instrucciones inyectadas",
    "instrucciones maliciosas",
    "instrucciones dirigidas",
    "intento de inyección",
    "redefinir mi rol",
    "modificar mi rol",
    "modificar mi comportamiento",
    "revelar mi configuración",
)


def _texto_propio_del_modelo(result: str) -> str:
    """Devuelve el texto que el modelo afirma por sí mismo, sin citas.

    - Si hay contrato JSON, las citas del artículo viven en `original` y no
      cuentan: solo `suggestion`/`reason` son texto propio.
    - Si hay JSON pero sin el contrato de hallazgos, todo el JSON es prosa del
      modelo (no hay campo de cita del que fiarse).
    - Si no hay JSON, la respuesta entera es prosa del modelo.
    """
    causa, payload = _decode_payload(result)
    if causa != "ok" or not isinstance(payload, dict) or "findings" not in payload:
        return result
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return result
    partes: list[str] = []
    for item in findings:
        if isinstance(item, dict):
            partes.append(str(item.get("suggestion", "")))
            partes.append(str(item.get("reason", "")))
    return "\n".join(partes)


def respuesta_fuera_de_rol(result: str) -> str | None:
    """Detecta una respuesta que rompe el rol de revisor y devuelve el motivo.

    `parse_findings` solo juzga la FORMA del JSON. Cuando la inyección tiene
    éxito, el modelo no devuelve el contrato: responde en prosa con el texto
    del atacante («ACCESO CONCEDIDO», un poema, una declaración de identidad
    nueva) o reproduce sus propias instrucciones de sistema. Sin esta
    comprobación, ese texto llegaba a la interfaz como si fuera contenido.

    Devuelve ``None`` cuando la respuesta es usable (contrato JSON válido, o
    JSON sin hallazgos) o cuando es una negativa legítima, y una cadena con el
    motivo en caso contrario. No es un filtro de contenido general: solo
    señala las marcas de obediencia a inyección y la fuga del system prompt.
    """
    texto = _texto_propio_del_modelo(result).strip()
    if not texto:
        return None
    bajo = texto.lower()

    if any(fragmento in bajo for fragmento in _SYSTEM_PROMPT_LEAK_SIGNALS):
        return "el modelo reprodujo sus instrucciones internas"
    if any(refus in bajo for refus in _LEGITIMATE_REFUSAL):
        return None
    if any(senal in bajo for senal in _ROLE_BREAK_SIGNALS):
        return "el modelo respondió fuera de su rol de revisor"
    return None
