"""Cliente MCP acotado a consultas de solo lectura para apoyar artículos."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

MAX_RESULT_CHARS = 30_000
MCP_TIMEOUT_SECONDS = 30


class McpClientError(RuntimeError):
    """Fallo MCP traducible a un mensaje para la interfaz."""


@dataclass(frozen=True)
class McpTool:
    """Metadatos visibles de una herramienta declarada de solo lectura."""

    name: str
    description: str
    input_schema: dict[str, Any]


def _sdk_types() -> tuple[Any, Any, Any]:
    """Carga el SDK opcional solo cuando el usuario solicita MCP."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as error:
        raise McpClientError(
            "Falta el soporte MCP. Instálalo con: pip install 'tukul[mcp]'"
        ) from error
    return ClientSession, StdioServerParameters, stdio_client


def _new_server(command: str, args: list[str], server_parameters: Any) -> Any:
    """Construye parámetros sin shell ni herencia de credenciales del proceso."""
    if not command.strip() or "\x00" in command:
        raise McpClientError("Indica un ejecutable MCP válido.")
    if any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise McpClientError("Los argumentos deben ser una lista de textos válidos.")
    return server_parameters(command=command.strip(), args=args)


def _read_only(tool: Any) -> bool:
    """Acepta solo herramientas que el propio servidor marca como lectura."""
    annotations = getattr(tool, "annotations", None)
    if annotations is None:
        return False
    value = getattr(annotations, "readOnlyHint", None)
    if value is None and hasattr(annotations, "model_dump"):
        value = annotations.model_dump(by_alias=True).get("readOnlyHint")
    return value is True


async def _list_tools(command: str, args: list[str]) -> list[McpTool]:
    client_session_type, server_parameters_type, stdio_client = _sdk_types()
    server = _new_server(command, args, server_parameters_type)
    async with stdio_client(server) as (read_stream, write_stream):
        async with client_session_type(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                McpTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=(
                        tool.inputSchema
                        if isinstance(tool.inputSchema, dict)
                        else {}
                    ),
                )
                for tool in result.tools
                if _read_only(tool)
            ]


def list_read_only_tools(command: str, args: list[str]) -> list[McpTool]:
    """Conecta, enumera herramientas MCP de solo lectura y cierra el proceso."""
    try:
        return asyncio.run(asyncio.wait_for(
            _list_tools(command, args), timeout=MCP_TIMEOUT_SECONDS))
    except McpClientError:
        raise
    except TimeoutError as error:
        raise McpClientError("El servidor MCP tardó demasiado en responder.") from error
    except Exception as error:
        raise McpClientError(f"No se pudo conectar con el servidor MCP: {error}") from error


async def _call_tool(command: str, args: list[str], name: str,
                     arguments: dict[str, Any]) -> str:
    client_session_type, server_parameters_type, stdio_client = _sdk_types()
    server = _new_server(command, args, server_parameters_type)
    rejection: str | None = None
    output = ""

    async with stdio_client(server) as (read_stream, write_stream):
        async with client_session_type(read_stream, write_stream) as session:
            await session.initialize()
            available = await session.list_tools()
            tool = next((item for item in available.tools if item.name == name), None)
            if tool is None or not _read_only(tool):
                rejection = (
                    "La herramienta no está disponible o no está marcada como solo lectura."
                )
            else:
                result = await session.call_tool(name, arguments)
                if getattr(result, "isError", False):
                    rejection = "El servidor MCP indicó que la consulta falló."
                else:
                    parts = [
                        block.text for block in (getattr(result, "content", None) or [])
                        if isinstance(getattr(block, "text", None), str)
                    ]
                    structured = getattr(result, "structuredContent", None)
                    if structured:
                        parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
                    output = "\n\n".join(parts).strip()
                    if not output:
                        output = "La herramienta no devolvió texto visible."

    if rejection:
        raise McpClientError(rejection)
    return output[:MAX_RESULT_CHARS]


def call_read_only_tool(command: str, args: list[str], name: str,
                        arguments: dict[str, Any]) -> str:
    """Ejecuta una herramienta aún marcada como solo lectura y limita su salida."""
    if not isinstance(arguments, dict):
        raise McpClientError("Los argumentos de la herramienta deben ser un objeto JSON.")
    try:
        return asyncio.run(asyncio.wait_for(
            _call_tool(command, args, name, arguments), timeout=MCP_TIMEOUT_SECONDS))
    except McpClientError:
        raise
    except TimeoutError as error:
        raise McpClientError("La consulta MCP superó el límite de 30 segundos.") from error
    except Exception as error:
        raise McpClientError(f"No se pudo consultar la herramienta MCP: {error}") from error
