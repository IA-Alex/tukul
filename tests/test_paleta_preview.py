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


def _pixeles_de_png(datos: bytes) -> tuple[int, int, set[bytes]]:
    """Devuelve (ancho, alto, colores distintos) leyendo un PNG RGB de 8 bits.

    Sin dependencias: descomprime los IDAT y deshace los filtros de línea
    (Sub, Up, Average, Paeth), que los codificadores aplican por defecto.
    """
    import struct
    import zlib

    ancho, alto, profundidad, tipo = struct.unpack(">IIBB", datos[16:26])
    assert profundidad == 8 and tipo == 2, "Se espera PNG RGB de 8 bits"

    pos = 8
    idat = b""
    while pos < len(datos):
        longitud = struct.unpack(">I", datos[pos:pos + 4])[0]
        if datos[pos + 4:pos + 8] == b"IDAT":
            idat += datos[pos + 8:pos + 8 + longitud]
        pos += 12 + longitud

    crudo = zlib.decompress(idat)
    ancho_fila = ancho * 3 + 1
    anterior = bytearray(ancho * 3)
    pixeles: set[bytes] = set()
    for y in range(alto):
        inicio = y * ancho_fila
        filtro = crudo[inicio]
        fila = bytearray(crudo[inicio + 1:inicio + ancho_fila])
        for i in range(len(fila)):
            izq = fila[i - 3] if i >= 3 else 0
            arriba = anterior[i]
            arriba_izq = anterior[i - 3] if i >= 3 else 0
            if filtro == 1:
                fila[i] = (fila[i] + izq) & 0xFF
            elif filtro == 2:
                fila[i] = (fila[i] + arriba) & 0xFF
            elif filtro == 3:
                fila[i] = (fila[i] + (izq + arriba) // 2) & 0xFF
            elif filtro == 4:
                estimado = izq + arriba - arriba_izq
                pa, pb, pc = (abs(estimado - izq), abs(estimado - arriba),
                              abs(estimado - arriba_izq))
                pred = izq if (pa <= pb and pa <= pc) else (arriba if pb <= pc else arriba_izq)
                fila[i] = (fila[i] + pred) & 0xFF
        anterior = fila
        for x in range(0, len(fila), 3):
            pixeles.add(bytes(fila[x:x + 3]))
    return ancho, alto, pixeles


def test_la_captura_no_queda_desfasada_de_la_paleta():
    """La IMAGEN debe contener los colores vigentes, no solo el HTML.

    `test_los_colores_de_la_hoja_coinciden_con_la_paleta` compara el HTML
    generado, así que un PNG viejo pasaba igual: el README enseñaba colores
    que ya no existían. Aquí se leen los píxeles del PNG y se exige que
    aparezcan las capas y el acento de los dos temas.

    Si falla por un cambio de paleta intencionado, regenera la captura.
    """
    from tukul_ui import estilo as es

    datos = IMAGEN.read_bytes()
    assert datos[:8] == _SOLO_PNG, "La captura no es un PNG"
    _ancho, _alto, pixeles = _pixeles_de_png(datos)

    esperados = {
        bytes.fromhex(es.PALETAS[tema][clave].lstrip("#").upper())
        for tema in ("dark", "light")
        for clave in ("fondo", "superficie_alta", "acento")
    }
    assert esperados <= pixeles, (
        "La captura no contiene los colores vigentes; regenérala con "
        "`python scripts/paleta_preview.py` y una captura de la hoja"
    )


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
