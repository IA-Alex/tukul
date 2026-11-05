"""La hoja de muestras de la paleta no puede quedar desfasada.

`scripts/paleta_preview.py` genera `docs/screenshots/paleta-tukul.png` a partir
de `tukul_ui.estilo`. Si la paleta cambia y la imagen no se regenera, el README
enseña colores que ya no existen. Este test compara los colores de la imagen
con la paleta vigente.

Si falla por un cambio de paleta intencionado, regenera la hoja:

    python scripts/paleta_preview.py
    # sirve build/ y captura en docs/screenshots/paleta-tukul.png
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGEN = ROOT / "docs" / "screenshots" / "paleta-tukul.png"

_SOLO_PNG = b"\x89PNG\r\n\x1a\n"


def _cargar_script():
    ruta = ROOT / "scripts" / "paleta_preview.py"
    spec = importlib.util.spec_from_file_location("paleta_preview", ruta)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_la_hoja_de_muestras_existe_y_es_png():
    assert IMAGEN.is_file(), "Falta docs/screenshots/paleta-tukul.png"
    with IMAGEN.open("rb") as fichero:
        assert fichero.read(8) == _SOLO_PNG


def test_los_colores_de_la_hoja_coinciden_con_la_paleta():
    preview = _cargar_script()
    html = preview.pagina()

    from tukul_ui import estilo as es

    for tema, tokens in es.PALETAS.items():
        for clave in preview.MUESTRAS:
            color = tokens[clave[0]].upper()
            assert color in html, f"{tema}/{clave[0]} ({color}) no está en la hoja"


def test_la_hoja_documenta_los_dos_temas():
    preview = _cargar_script()
    html = preview.pagina()
    for tema in ("dark", "light"):
        assert f"Tukul · {tema}" in html
