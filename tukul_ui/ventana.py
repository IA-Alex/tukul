"""Saneado de estado de ventana: geometría, zoom y recientes.

Funciones puras que convierten lo persistido en `estado.json` —que puede venir
de otro monitor, de otra resolución, de una sesión remota o estar corrupto— en
valores utilizables, sin tocar Tk. Al ser puras se prueban sin montar la
ventana y `TukulApp` solo delega.

Se extraen de `app.py` porque son el tipo de lógica que más se degrada cuando
vive dentro de un god object: reglas de acotado y normalización que nadie lee
porque están rodeadas de 3.000 líneas de interfaz.
"""

from __future__ import annotations

import re

from tukul_ui import estilo as es

# Geometría «ancho x alto ±x ±y». El signo va DENTRO del grupo para que las
# dos negaciones se elijan por separado: Tk las escribe de verdad como
# «1920x1011+-61+-23» cuando la ventana queda a la izquierda o por encima del
# origen del escritorio. Un patrón que solo admitiera «[+-]\d+» no casa con
# «+-61» y la lectura descartaba la geometría guardada, abriendo con el
# tamaño por defecto en lugar de donde la persona dejó la ventana.
PATRON_GEOMETRIA = re.compile(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)")

# Topes de tamaño mínimo: el suelo de ancho es el de la barra superior (por
# debajo, el nombre del artículo deja de verse). `app.py` los usa también al
# construir la ventana, por eso se declaran aquí y se importan.
ANCHO_MINIMO_VENTANA = 1120
ALTO_MINIMO_VENTANA = 540


def geometria_saneada(guardada: object, pantalla_ancho: int,
                      pantalla_alto: int) -> str | None:
    """Normaliza y acota una geometría; None si no es utilizable.

    Devuelve siempre el formato canónico «AxA+x+y» (coordenadas no
    negativas), de modo que lo restaurado y lo que se escribe en
    `estado.json` comparten una única representación. Una geometría de otro
    monitor, de otra resolución o de una sesión remota puede no caber en el
    escritorio actual; Tk la aceptaría, pero dejaría controles fuera del
    viewport. Ante valores no utilizables o pantallas sin dimensiones se
    descarta sin lanzar excepciones.
    """
    if not isinstance(guardada, str):
        return None
    if pantalla_ancho <= 0 or pantalla_alto <= 0:
        return None
    coincidencia = PATRON_GEOMETRIA.fullmatch(guardada.strip())
    if coincidencia is None:
        return None

    ancho, alto, x, y = (int(valor.replace("+-", "-"))
                         for valor in coincidencia.groups())
    # Mantiene un margen visible para que la barra del sistema y los
    # bordes no oculten la ventana completa en escritorios pequeños.
    # El suelo de ancho es el de la barra superior: por debajo, el nombre
    # del artículo deja de verse aunque la ventana «quepa» en pantalla.
    # Pero ese suelo no puede exceder la pantalla: en un portátil de
    # 1024 px una ventana de 1120 quedaría cortada por el borde derecho.
    suelo_ancho = min(ANCHO_MINIMO_VENTANA, max(1, pantalla_ancho - 32))
    suelo_alto = min(ALTO_MINIMO_VENTANA, max(1, pantalla_alto - 64))
    ancho = min(max(ancho, suelo_ancho), max(suelo_ancho, pantalla_ancho - 32))
    alto = min(max(alto, suelo_alto), max(suelo_alto, pantalla_alto - 64))
    x = min(max(x, 0), max(0, pantalla_ancho - ancho))
    y = min(max(y, 0), max(0, pantalla_alto - alto))
    return f"{ancho}x{alto}+{x}+{y}"


def zoom_validado(valor: object) -> float:
    """Convierte el zoom persistido a un factor acotado; 1.0 ante basura."""
    try:
        zoom = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return max(es.ZOOM_MIN, min(es.ZOOM_MAX, zoom))


def recientes_validados(valor: object) -> list[str]:
    """Filtra la lista de recientes persistida a rutas útiles, con tope."""
    if not isinstance(valor, list):
        return []
    return [ruta for ruta in valor if isinstance(ruta, str) and ruta][:10]
