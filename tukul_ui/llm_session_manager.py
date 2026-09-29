"""Gestiona sesiones de LLM con manejo robusto de excepciones."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable

from tukul_core.llm import LLMClient, LlmError
from tukul_core.models import ChatMessage, LlmProfile
from tukul_core.prompting import build_editor_prompt


class LLMSessionManager:
    """Orquesta requests, streaming y cancelación con error handling robusto."""

    def __init__(self) -> None:
        self.client = LLMClient()
        # request_id y request_active ahora se manejan vía RequestState en app.py
        self.cancel_event: threading.Event | None = None

    def stream_response(
        self,
        profile: LlmProfile,
        api_key: str,
        article: str,
        packet: str,
        conversation: Iterable[ChatMessage],
        on_chunk: Callable[[str], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[str, tuple[int | None, int | None]], None],
        request_id: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """
        Stream respuesta con error handling robusto.
        Ejecutar en thread separado.
        """
        # El evento de cancelación debe viajar con la petición: leerlo del manager
        # dejaba una ventana en la que una petición nueva sobrescribía el evento de
        # la anterior mientras su hilo aún no lo había capturado (cancelación cruzada).
        if cancel_event is None:
            cancel_event = self.cancel_event

        # Early return si cancelado antes de iniciar
        if cancel_event and cancel_event.is_set():
            return

        try:
            # Validar input (puede fallar si es demasiado grande)
            try:
                prompt = build_editor_prompt(article, packet, conversation)
            except (ValueError, TypeError, OSError) as error:
                on_error(f"Error al preparar prompt: {error}")
                return

            # Stream con captura amplia de excepciones
            try:
                collected = self._collect_stream(
                    profile, api_key, prompt, request_id, cancel_event, on_chunk
                )
                if collected is None:
                    return  # Cancelado a mitad: nadie espera callback.
                result, usage = collected
                if not result.strip():
                    raise LlmError("El proveedor devolvió una respuesta vacía.")

                # Pasar resultado y tokens de uso reales
                on_complete(result, usage)
                return

            except LlmError as error:
                on_error(str(error))
                return
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
                on_error(
                    f"Error de conexión o parsing: {error.__class__.__name__}: {error}"
                )
                return

        except Exception as error:
            # Catch-all para errores inesperados
            on_error(f"Error interno inesperado: {error}")

    def _collect_stream(
        self,
        profile: LlmProfile,
        api_key: str,
        prompt: str,
        request_id: int | None,
        cancel_event: threading.Event | None,
        on_chunk: Callable[[str], None],
    ) -> tuple[str, tuple[int | None, int | None]] | None:
        """Acumula la respuesta completa. Devuelve (texto, uso), o None si se canceló."""
        chunks: list[str] = []
        usage: tuple[int | None, int | None] = (None, None)
        # Techo de RAM derivado del perfil (~4 bytes/token UTF-8, factor 2x) en vez
        # de un límite fijo que puede no encajar con la configuración del modelo.
        max_response_bytes = max(2 * 1024 * 1024, profile.max_output_tokens * 4 * 2)
        accumulated_bytes = 0  # Evita el coste cuadrático de len("".join(chunks))

        for chunk in self.client.stream(profile, api_key, prompt, request_id, cancel_event):
            if cancel_event and cancel_event.is_set():
                return None
            if isinstance(chunk.content, str) and chunk.content:
                accumulated_bytes = self._accept_chunk(
                    chunk.content, accumulated_bytes, max_response_bytes
                )
                chunks.append(chunk.content)
                on_chunk(chunk.content)
            if chunk.input_tokens is not None or chunk.output_tokens is not None:
                usage = (chunk.input_tokens, chunk.output_tokens)
        return "".join(chunks), usage

    @staticmethod
    def _accept_chunk(content: str, accumulated: int, ceiling: int) -> int:
        """Contabiliza un fragmento contra el techo de RAM. Devuelve el acumulado.

        Solo mide el techo: no limita tokens, eso lo decide el proveedor.
        """
        chunk_bytes = len(content.encode("utf-8"))
        if accumulated + chunk_bytes > ceiling:
            raise LlmError(
                f"La respuesta excede el límite de memoria de "
                f"{ceiling / (1024 * 1024):.1f}MB. Respuesta truncada."
            )
        return accumulated + chunk_bytes

    def cancel(self, request_id: int) -> None:
        """Cancela request activo."""
        if self.cancel_event:
            self.cancel_event.set()
        self.client.cancel(request_id)
        # request_id y request_active ahora se manejan en app.py (TukulApp)
