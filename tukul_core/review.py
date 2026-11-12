from __future__ import annotations

import ast
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
    """Localiza y decodifica el JSON de la respuesta; devuelve la causa si no.

    Acepta tanto el objeto del contrato (`{"findings": [...]}`) como un **array
    raíz** de hallazgos. El segundo caso se observó contra DeepInfra: el modelo
    devuelve de forma esporádica `[{...}]` sin el envoltorio que pide el
    contrato. Antes, al buscar solo el primer `{`, se decodificaba **un único
    elemento** del array y `diagnose_findings` lo descartaba como
    `esquema_ajeno`, perdiendo los hallazgos en silencio. La aplicación no puede
    depender de la obediencia del modelo para la forma, así que un array de
    objetos de hallazgo se normaliza al contrato canónico.
    """
    clean = result.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if len(clean) > MAX_RESULT_CHARS:
        return "truncado", None
    # El JSON raíz puede empezar por «{» (contrato) o por «[» (array de
    # hallazgos). Se toma el que aparezca antes: decodificar desde el «{» de un
    # array devolvería solo su primer elemento.
    inicio_objeto = clean.find("{")
    inicio_array = clean.find("[")
    candidatos = [i for i in (inicio_objeto, inicio_array) if i >= 0]
    if not candidatos:
        return "sin_json", None
    start = min(candidatos)
    try:
        payload, _end = json.JSONDecoder().raw_decode(clean[start:])
    except ValueError:
        # Hay una llave de apertura pero no un valor completo: corte o
        # respuesta a medias, que es información distinta de una prosa.
        return "truncado", None
    if isinstance(payload, list):
        # Un array de objetos de hallazgo es el contrato sin el envoltorio:
        # se normaliza. Un array de otra cosa (p. ej. cadenas) se deja tal cual
        # para que `diagnose_findings` lo clasifique como esquema ajeno.
        if payload and all(isinstance(item, dict) for item in payload):
            payload = {"findings": payload}
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


def omitted_reasons(result: str) -> list[str]:
    """Motivos que el modelo declara haber omitido a petición del usuario.

    El campo ``omitted`` es opcional y solo aparece cuando el modelo respeta una
    petición de omitir hallazgos (ver ``SYSTEM_PROMPT``). Sin esta función, una
    revisión vacía por obediencia era indistinguible de un artículo sin errores:
    ambas llegan como ``findings: []``. Se devuelve una lista vacía cuando no hay
    JSON válido o cuando el campo está ausente o mal formado, de modo que el
    comportamiento previo queda intacto.

    El formato que devuelve el modelo NO es fiable: sin un ejemplo literal en el
    prompt llegó a mandar la representación de un objeto dentro de la cadena
    (``"{'original': 'introdución', 'reason': '…'}"``). La aplicación no puede
    depender de su obediencia para el formato, así que aquí se normaliza: cada
    elemento se convierte en el texto del motivo, esté como cadena simple, como
    objeto JSON con ``reason``/``motivo`` o como el `repr` de un dict de Python.
    """
    causa, payload = _decode_payload(result)
    if causa != "ok" or not isinstance(payload, dict):
        return []
    omitted = payload.get("omitted")
    if not isinstance(omitted, list):
        return []
    motivos: list[str] = []
    for elemento in omitted:
        motivo = _texto_de_motivo(elemento)
        if motivo:
            motivos.append(motivo)
    return motivos


# Claves habituales del motivo, en orden de preferencia.
_CLAVES_MOTIVO = ("reason", "motivo", "razón", "razon")


def _texto_de_motivo(elemento: object) -> str:
    """Extrae un motivo legible de cualquiera de las formas observadas.

    Acepta: una cadena simple; un objeto JSON con una clave de motivo; y la
    representación textual de un dict de Python (comillas simples, que no es
    JSON válido). Si nada de eso da texto, se conserva la cadena original como
    último recurso: es preferible un motivo imperfecto a perder la señal.
    """
    if isinstance(elemento, dict):
        for clave in _CLAVES_MOTIVO:
            valor = elemento.get(clave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        return ""
    if not isinstance(elemento, str):
        return ""
    texto = elemento.strip()
    if not texto:
        return ""
    if texto.startswith("{"):
        # Parece un objeto: o se extrae un motivo legible, o se descarta. Devolver
        # el texto crudo mostraría al usuario un `repr` roto o un dict sin motivo.
        objeto = _parsear_repr_de_dict(texto)
        if objeto is None:
            return ""
        for clave in _CLAVES_MOTIVO:
            valor = objeto.get(clave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        return ""
    return texto


def _parsear_repr_de_dict(texto: str) -> dict | None:
    """Convierte el `repr` de un dict de Python en un dict, o None.

    Se limita deliberadamente a un ``{...}`` con comillas simples dentro: no
    evalúa código ni usa `ast.literal_eval` sobre la salida del modelo, que es
    un dato no confiable. Solo se acepta el resultado si JSON lo puede leer tras
    normalizar las comillas, y únicamente se consumen claves de texto conocidas.
    """
    if not (texto.startswith("{") and texto.endswith("}")):
        return None
    try:
        objeto = ast.literal_eval(texto)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(objeto, dict):
        return None
    # Solo se acepta como dict si sus valores son simples: evita materializar
    # estructuras anidadas o llamadas que `literal_eval` rechazaría de todos
    # modos, y deja el resto como texto.
    if not all(isinstance(v, (str, int, float, bool, type(None))) for v in objeto.values()):
        return None
    return objeto


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
