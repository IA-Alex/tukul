"""Integración real del cliente con un servidor MCP local por stdio."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from tukul_core.mcp_client import (
    MAX_RESULT_CHARS,
    McpClientError,
    call_read_only_tool,
    list_read_only_tools,
)

SERVER_SOURCE = textwrap.dedent(
    """
    import asyncio
    import os
    from typing import Any

    import mcp.server.stdio
    import mcp.types as types
    from mcp.server.lowlevel import NotificationOptions, Server
    from mcp.server.models import InitializationOptions

    server = Server("tukul-test-server")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="lookup",
                description="Devuelve el texto solicitado.",
                inputSchema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                annotations=types.ToolAnnotations(readOnlyHint=True),
            ),
            types.Tool(
                name="mutate",
                description="Herramienta que no es de solo lectura.",
                inputSchema={"type": "object"},
                annotations=types.ToolAnnotations(readOnlyHint=False),
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        if name == "lookup":
            value = arguments["value"]
            if value == "__env__":
                value = os.environ.get("TUKUL_TEST_SECRET", "not inherited")
            if value == "__error__":
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="failure")], isError=True
                )
            return [types.TextContent(type="text", text=value)]
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="rejected")], isError=True
        )

    async def main() -> None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="tukul-test-server",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    asyncio.run(main())
    """
)


@pytest.fixture()
def servidor_mcp(tmp_path: Path) -> tuple[str, list[str]]:
    script = tmp_path / "servidor_mcp.py"
    script.write_text(SERVER_SOURCE, encoding="utf-8")
    return sys.executable, [str(script)]


def test_stdio_real_filtra_herramientas_y_ejecuta_solo_lectura(servidor_mcp):
    command, args = servidor_mcp

    tools = list_read_only_tools(command, args)

    assert [tool.name for tool in tools] == ["lookup"]
    assert tools[0].description == "Devuelve el texto solicitado."
    assert call_read_only_tool(command, args, "lookup", {"value": "respuesta MCP"}) == (
        "respuesta MCP"
    )


def test_stdio_real_rechaza_herramienta_sin_marca_de_solo_lectura(servidor_mcp):
    command, args = servidor_mcp

    with pytest.raises(McpClientError, match="no está marcada como solo lectura"):
        call_read_only_tool(command, args, "mutate", {})


def test_stdio_real_limpia_el_entorno_y_acota_la_salida(servidor_mcp, monkeypatch):
    command, args = servidor_mcp
    monkeypatch.setenv("TUKUL_TEST_SECRET", "sentinel")

    secreto = call_read_only_tool(command, args, "lookup", {"value": "__env__"})
    resultado = call_read_only_tool(
        command, args, "lookup", {"value": "x" * (MAX_RESULT_CHARS + 500)}
    )

    assert secreto == "not inherited"
    assert len(resultado) == MAX_RESULT_CHARS


def test_stdio_real_informa_error_de_herramienta(servidor_mcp):
    command, args = servidor_mcp

    with pytest.raises(McpClientError, match="indicó que la consulta falló"):
        call_read_only_tool(command, args, "lookup", {"value": "__error__"})
