#!/usr/bin/env python3
"""Punto de entrada estable de Articulador."""

from __future__ import annotations

import argparse
from pathlib import Path

from articulador_core import storage
from articulador_ui.app import ArticuladorApp


def open_initial_document(app: ArticuladorApp, path: Path) -> None:
    """Abre el documento opcional de la línea de órdenes.

    La lectura, el manejo de errores y la sesión limpia los resuelve
    DocumentManager a través de app.load_document.
    """
    app.load_document(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Editor conversacional local para artículos Markdown.")
    parser.add_argument("--config", type=Path, default=storage.CONFIG_PATH, help="Ruta al archivo TOML de perfiles LLM")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Carpeta de artículos usada como contexto local")
    parser.add_argument("--health", action="store_true", help="Imprime el diagnóstico de la instalación y sale")
    parser.add_argument("document", type=Path, nargs="?", help="Artículo Markdown para abrir")
    args = parser.parse_args()

    if args.health:
        # Diagnóstico sin abrir ventana: útil cuando la app no arranca o el
        # llavero/config no están accesibles.
        from articulador_core.health import check_health, status_string

        status = check_health()
        print(status_string(status))
        raise SystemExit(0 if status.is_healthy else 1)

    if not args.workspace.is_dir():
        parser.error(f"El workspace no es una carpeta existente: {args.workspace}")

    app = ArticuladorApp(args.config, args.workspace)
    if args.document:
        open_initial_document(app, args.document)
    app.mainloop()


if __name__ == "__main__":
    main()
