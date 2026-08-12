"""Gestiona sesiones de LLM con manejo robusto de excepciones."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable

from articulador_core.llm import LLMClient, LlmError
from articulador_core.models import ChatMessage, LlmProfile
from articulador_core.prompting import build_editor_prompt


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
            chunks = []
            usage = (None, None)
            # FIX: Calcular límite de RAM en función de max_output_tokens del profile
            # Conversión: ~4 bytes/token en UTF-8 (worst case), con factor de seguridad 2x
            # Esto evita hardcoded limits que pueden no coincidir con la config del modelo
            max_response_bytes = max(2 * 1024 * 1024, profile.max_output_tokens * 4 * 2)
            # Acumulador para evitar cálculo cuadrático len("".join(chunks))
            accumulated_bytes = 0

            try:
                for chunk in self.client.stream(
                    profile, api_key, prompt, request_id, cancel_event
                ):
                    if cancel_event and cancel_event.is_set():
                        return

                    if chunk.content:
                        # Validar que chunk.content es string antes de acumular
                        if not isinstance(chunk.content, str):
                            continue

                        # Verificar solo techo de RAM (no limitar tokens, confiar en proveedor)
                        chunk_bytes = len(chunk.content.encode("utf-8"))
                        if accumulated_bytes + chunk_bytes > max_response_bytes:
                            raise LlmError(f"La respuesta excede el límite de memoria de {max_response_bytes / (1024*1024):.1f}MB. Respuesta truncada.")

                        chunks.append(chunk.content)
                        accumulated_bytes += chunk_bytes  # ← Acumulador en bytes
                        on_chunk(chunk.content)

                    if (
                        chunk.input_tokens is not None
                        or chunk.output_tokens is not None
                    ):
                        usage = (chunk.input_tokens, chunk.output_tokens)

                result = "".join(chunks)
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

    def cancel(self, request_id: int) -> None:
        """Cancela request activo."""
        if self.cancel_event:
            self.cancel_event.set()
        self.client.cancel(request_id)
        # request_id y request_active ahora se manejan en app.py (ArticuladorApp)
