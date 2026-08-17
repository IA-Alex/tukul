#!/usr/bin/env python3
"""Punto de entrada estable de Articulador."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from articulador_core import storage
from articulador_ui.app import ArticuladorApp


def _forzar_utf8_en_consola() -> None:
    """La consola de Windows arranca en cp1252 (no UTF-8): el primer emoji o
    acento que imprime health.py, o que registra el logger de consola, tronaba
    con UnicodeEncodeError y tumbaba --health antes de mostrar nada.

    sys.stdout es el mismo objeto que capturó el StreamHandler de
    logging_config.py (creado al importar articulador_core.storage, arriba);
    reconfigurarlo en el mismo objeto también corrige la salida por logger, no
    solo los print(). None en builds sin consola (`pyinstaller --windowed`);
    errors="replace" para no romper por un carácter aislado que ni así se
    pueda representar.
    """
    for stream in (sys.stdout, sys.stderr):
        # getattr(): la firma de sys.stdout en el stub de typing (TextIO) no
        # declara reconfigure(), aunque TextIOWrapper (lo real en CPython) sí
        # la tiene desde 3.7. Evita el falso positivo de mypy sin acallarlo.
        reconfigurar = getattr(stream, "reconfigure", None)
        if reconfigurar is not None:
            try:
                reconfigurar(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def open_initial_document(app: ArticuladorApp, path: Path) -> None:
    """Abre el documento opcional de la línea de órdenes.

    La lectura, el manejo de errores y la sesión limpia los resuelve
    DocumentManager a través de app.load_document.
    """
    app.load_document(path)


def main() -> None:
    _forzar_utf8_en_consola()
    parser = argparse.ArgumentParser(description="Editor conversacional local para artículos Markdown.")
    parser.add_argument("--config", type=Path, default=storage.CONFIG_PATH, help="Ruta al archivo TOML de perfiles LLM")
    parser.add_argument("--health", action="store_true", help="Imprime el diagnóstico de la instalación y sale")
    parser.add_argument("document", type=Path, nargs="?", help="Artículo Markdown para abrir")
    args = parser.parse_args()

    if args.health:
        # Diagnóstico sin abrir ventana: útil cuando la app no arranca o el
        # llavero/config no están accesibles.
        from articulador_core.health import check_health, status_string

        # Debe diagnosticar el config que pidió la CLI, no siempre el de por defecto.
        status = check_health(args.config)
        print(status_string(status))
        # Salida 1 solo si algo está roto: una instalación nueva tiene avisos
        # (sin carpeta de config, sin perfiles) y sigue siendo utilizable.
        raise SystemExit(1 if status.has_errors else 0)

    app = ArticuladorApp(args.config)
    if args.document:
        open_initial_document(app, args.document)
    app.mainloop()


if __name__ == "__main__":
    main()
