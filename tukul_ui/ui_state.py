"""Caché de conversaciones por documento para el estado de interfaz.

Los métodos privados de `TukulApp` que mantenían esta caché operaban
directamente sobre la estructura `conversations` de `ui_state`. Al extraerlos
como funciones puras se pueden razonar y probar sin instanciar la ventana de
Tk: la app solo delega, y `estado.json` deja de depender de la sesión de UI.
"""
from __future__ import annotations

from pathlib import Path

from tukul_core.models import ChatMessage

MAX_CONVERSATION_MESSAGE_CHARS = 200_000
MAX_CONVERSATION_CHARS = 1_000_000


def restaurar_conversacion(conversaciones: object, path: Path | None) -> list[ChatMessage]:
    """Conversación persistida de un documento, o [] si no existe o es inválida.

    Descarta cualquier ítem malformado (rol o contenido no textual) en vez de
    fallar: el estado es un JSON local que puede corromperse.
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
            content = item["content"]
            if len(content) > MAX_CONVERSATION_MESSAGE_CHARS:
                continue
            if total_chars + len(content) > MAX_CONVERSATION_CHARS:
                continue
            restaurada.append(ChatMessage(item["role"], content))
            total_chars += len(content)
    return restaurada


def persistir_conversacion(
    conversaciones: object, path: Path, turnos: list[ChatMessage], max_turnos: int = 30
) -> dict:
    """Devuelve el mapa de conversaciones con la del documento actualizada.

    Si `conversaciones` no es un dict (estado corrupto) se parte de un mapa
    vacío. Solo se conservan los `max_turnos` más recientes del documento.
    """
    base = dict(conversaciones) if isinstance(conversaciones, dict) else {}
    persisted = []
    total_chars = 0
    for message in reversed(turnos[-max_turnos:]):
        if len(message.content) > MAX_CONVERSATION_MESSAGE_CHARS:
            continue
        if total_chars + len(message.content) > MAX_CONVERSATION_CHARS:
            break
        persisted.append({"role": message.role, "content": message.content})
        total_chars += len(message.content)
    base[str(path)] = list(reversed(persisted))
    return base


def podar_conversaciones(conversaciones: dict, vigentes: set[str]) -> dict:
    """Conserva solo las conversaciones de los documentos vigentes.

    Vigente = sigue en «recientes» o es el documento activo. Sin esta poda,
    `estado.json` acumula para siempre una entrada por cada artículo abierto
    alguna vez.
    """
    return {ruta: turnos for ruta, turnos in conversaciones.items() if ruta in vigentes}
