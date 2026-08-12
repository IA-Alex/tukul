#!/usr/bin/env python3
"""Punto de entrada estable de Articulador."""

from __future__ import annotations

import argparse
from pathlib import Path

from articulador_core import storage
from articulador_ui.app import ArticuladorApp


def open_initial_document(app: ArticuladorApp, path: Path) -> None:
    """Open an optional CLI document without leaving a half-loaded session."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        app.show_error("No se pudo abrir el documento", f"{path}\n\n{error}")
        return
    app.load_document_content(path, content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Editor conversacional local para artículos Markdown.")
    parser.add_argument("--config", type=Path, default=storage.CONFIG_PATH, help="Ruta al archivo TOML de perfiles LLM")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Carpeta de artículos usada como contexto local")
    parser.add_argument("document", type=Path, nargs="?", help="Artículo Markdown para abrir")
    args = parser.parse_args()
    app = ArticuladorApp(args.config, args.workspace)
    if args.document:
        open_initial_document(app, args.document)
    app.mainloop()


if __name__ == "__main__":
    main()
