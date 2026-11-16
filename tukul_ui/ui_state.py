"""Caché de conversaciones por documento para el estado de interfaz.

Los métodos privados de `TukulApp` que mantenían esta caché operaban
directamente sobre la estructura `conversations` de `ui_state`. Al extraerlos
como funciones puras se pueden razonar y probar sin instanciar la ventana de
Tk: la app solo delega, y `estado.json` deja de depender de la sesión de UI.

Presupuesto único (no dos topes que se contradicen): todo lo que se guarda por
documento cabe en `MAX_CONVERSATION_CHARS` caracteres, y esa cifra se deriva
del tamaño máximo real de `estado.json` (`storage.MAX_UI_STATE_BYTES`). Antes
los límites eran 200 000 chars por mensaje y 1 000 000 por conversación,
mientras el archivo entero solo admitía 2 MiB: una respuesta larga acercaba el
archivo al tope, `save_ui_state` lo rechazaba completo y, al reabrir, la
conversación aparecía vacía sin ningún aviso.
"""
from __future__ import annotations

import json
from pathlib import Path

from tukul_core.models import ChatMessage
from tukul_core.storage import MAX_UI_STATE_BYTES

#: Techo por mensaje restaurado desde disco. Se conserva como cota independiente
#: del presupuesto total: un mensaje aislado desproporcionado no debe ocuparlo
#: todo, y un estado editado a mano fuera de la app sigue siendo input hostil.
MAX_CONVERSATION_MESSAGE_CHARS = 200_000

#: Presupuesto total por documento. Se calcula desde el tope del archivo en vez
#: de fijarse a mano para que no vuelva a desincronizarse.
MAX_CONVERSATION_CHARS = MAX_UI_STATE_BYTES // 4

#: Marca con la que se señala, dentro del propio mensaje, que se recortó al
#: guardarlo. Sin ella el texto reaparecería truncado sin explicación.
MARCA_RECORTE = "…[recortado al guardar para caber en el estado]"

def _serializar(conversacion: object) -> str:
    """Única forma de medir una conversación: la misma que usa `estado.json`.

    Se pasan los argumentos explícitos (y no un `**dict`) para que mypy pueda
    comprobarlos; el contrato es la pareja `ensure_ascii`/`separators`.
    """
    return json.dumps(conversacion, ensure_ascii=False, separators=(",", ":"))


def _cabe_en_presupuesto(conversacion: object) -> bool:
    """Comprueba el presupuesto sobre la serialización REAL, no una estimación.

    `ensure_ascii=False` importa: el texto en español ocupa un carácter, pero
    una versión escapada ocuparía hasta seis. Contar caracteres crudos sobre la
    codificación real evita que el margen se quede corto justo con los escritos
    para los que existe la app.
    """
    return len(_serializar(conversacion).encode("utf-8")) <= MAX_CONVERSATION_CHARS


def _recortar_al_limite(content: str, limite: int) -> str:
    """Recorta el texto a `limite` caracteres, sin partir un carácter compuesto."""
    if len(content) <= limite:
        return content
    return content[:max(0, limite - len(MARCA_RECORTE))] + MARCA_RECORTE


def restaurar_conversacion(conversaciones: object, path: Path | None) -> list[ChatMessage]:
    """Conversación persistida de un documento, o [] si no existe o es inválida.

    Descarta cualquier ítem malformado (rol o contenido no textual) en vez de
    fallar: el estado es un JSON local que puede corromperse.

    Lo que excede el techo se RECORTA, no se descarta. Descartarlo entero
    hacía desaparecer la respuesta del modelo —y, en el peor caso, también el
    turno del usuario— sin que nada lo indicara.
    """
    if path is None or not isinstance(conversaciones, dict):
        return []
    cruda = conversaciones.get(str(path))
    if not isinstance(cruda, list):
        return []
    restaurada: list[ChatMessage] = []
    total_chars = 0
    for item in cruda:
        if (isinstance(item, dict) and item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)):
            content = _recortar_al_limite(item["content"], MAX_CONVERSATION_MESSAGE_CHARS)
            resto = MAX_CONVERSATION_CHARS - total_chars
            if resto <= 0:
                break
            content = _recortar_al_limite(content, resto)
            restaurada.append(ChatMessage(item["role"], content))
            total_chars += len(content)
    return restaurada


def persistir_conversacion(
    conversaciones: object, path: Path, turnos: list[ChatMessage], max_turnos: int = 30
) -> dict:
    """Devuelve el mapa de conversaciones con la del documento actualizada.

    Si `conversaciones` no es un dict (estado corrupto) se parte de un mapa
    vacío. Solo se conservan los `max_turnos` más recientes del documento, y la
    conversación resultante cabe SIEMPRE en `MAX_CONVERSATION_CHARS` (comprobado
    sobre su serialización real). El recorte empieza por los turnos más
    antiguos, que son los que menos contexto aportan, y nunca descarta un turno
    por completo: un turno recortado conserva su rol y el final del texto.
    """
    base = dict(conversaciones) if isinstance(conversaciones, dict) else {}
    persistidos = [
        {"role": message.role, "content": message.content}
        for message in turnos[-max_turnos:]
        if isinstance(message.content, str)
    ]
    # Estrategia, de menos a más destructiva:
    #   1. descartar los turnos MÁS ANTIGUOS hasta que el resto quepa recortado
    #      (el historial reciente es el que sirve de contexto al modelo);
    #   2. recortar el mensaje más largo del resto hasta encajar del todo.
    # Así una respuesta larga no se borra: se abrevia con una marca visible, y
    # el historial nunca se vacía por exceso de tamaño.
    while persistidos and not _cabe_si_se_recorta(persistidos):
        persistidos.pop(0)
    while persistidos and not _cabe_en_presupuesto(persistidos):
        mas_largo = max(persistidos, key=lambda item: len(item["content"]))
        if not _abreviar(persistidos, mas_largo):
            persistidos.pop(0)
    base[str(path)] = persistidos
    return base


def _cabe_si_se_recorta(persistidos: list[dict]) -> bool:
    """¿Cabe si los mensajes se recortaran hasta la marca de recorte?

    Es la condición que decide si un turno se descarta o simplemente se abrevia.
    """
    vacio = [{"role": item["role"], "content": MARCA_RECORTE} for item in persistidos]
    return len(_serializar(vacio).encode("utf-8")) <= MAX_CONVERSATION_CHARS


def _abreviar(persistidos: list[dict], mas_largo: dict) -> bool:
    """Recorta el mensaje más largo para hacer sitio. False si ya no puede.

    El recorte se calibra por proporción del exceso (no de a un carácter) y se
    reintenta en bucle en `persistir_conversacion`, porque la serialización
    exacta incluye comillas escapadas y comas que no se pueden predecir a mano.
    """
    exceso = len(_serializar(persistidos).encode("utf-8")) - MAX_CONVERSATION_CHARS
    if exceso <= 0:
        return False
    actual = mas_largo["content"]
    # Un byte de exceso no equivale a un carácter (el UTF-8 y los escapes JSON
    # ocupan más de uno por carácter), así que se pide un margen extra y el
    # bucle de `persistir_conversacion` corrige si se queda corto. El suelo es
    # la marca de recorte: si ya no cabe ni el aviso, no hay nada honesto que
    # guardar de ese mensaje y devolver False deja que se descarte el turno.
    objetivo = len(actual) - exceso - (exceso // 4) - 16
    if objetivo < len(MARCA_RECORTE):
        return False
    mas_largo["content"] = _recortar_al_limite(actual, objetivo)
    return True


def podar_conversaciones(conversaciones: dict, vigentes: set[str]) -> dict:
    """Conserva solo las conversaciones de los documentos vigentes.

    Vigente = sigue en «recientes» o es el documento activo. Sin esta poda,
    `estado.json` acumula para siempre una entrada por cada artículo abierto
    alguna vez.
    """
    return {ruta: turnos for ruta, turnos in conversaciones.items() if ruta in vigentes}
