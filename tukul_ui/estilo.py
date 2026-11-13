"""Sistema visual de Tukul: identidad «Obsidiana y Jade».

El nombre viene del *tunkul*: un instrumento de percusión maya hecho con un
canuto cerrado por ambos extremos, con dos lengüetas talladas —una más gruesa
que otra— que al golpearlas con un bolillo emiten dos tonos, uno más agudo que
otro. Así lo recoge el Diccionario de americanismos (ASALE).

De ahí sale la paleta, y solo la paleta: el comportamiento no cambia.

- **Obsidiana** (`fondo`, `superficie`, `superficie_alta`): la piedra volcánica
  del altiplano, del negro profundo al gris piedra, con un matiz azul frío.
- **Estuco sombra** (`borde`): la junta entre los bloques de piedra; es
  divisoria, no pieza accionable, así que puede ser sutil.
- **Jade** (`acento`): el verde de la piedra tallada, reservado a la acción
  primaria y a la identidad. Su texto va en verde muy oscuro para máximo
  contraste sobre el jade.
- **Ámbar tunkul** (`acento_secundario`, expuesto como `VOZ_ASISTENTE`): el
  color de la madera del tambor, que nombra al asistente en el chat y marca las
  alertas.

Reglas del sistema, deliberadamente estrechas para que la interfaz se lea como
una sola pieza:

- **Dos paletas completas** (`dark`, `light`), centralizadas en `PALETAS`. Los
  atributos de módulo (`FONDO`, `SUPERFICIE`…) son SIEMPRE los del tema activo:
  `aplicar_tema()` los reasigna en bloque, así que no hay segunda fuente de
  verdad ni copias congeladas del color.
- **Un fondo** (`fondo`) y **dos superficies** (`superficie`, `superficie_alta`).
  La profundidad se expresa con esas tres capas.
- **Dos bordes con funciones distintas**: `borde` (divisoria sutil y hover) y
  `borde_control` (borde de las piezas accionables, ≥ 3:1 contra su fondo según
  WCAG 1.4.11). La obsidiana de `borde` es deliberadamente tenue como divisoria;
  las piezas que se pulsan o arrastran usan el tono más claro de `borde_control`.
- **Un acento** (`acento`, jade), reservado para la acción primaria y la
  identidad.
- **Escala tipográfica de tres tamaños**: `TIPO_SM`, `TIPO_MD`, `TIPO_LG`.
- **Espaciado de 4/8/12/16** (`ESP`). Ningún margen fuera de esa rejilla.

Los colores de estado (`ESTADO_*`) NO son acentos decorativos: son señal
funcional y nunca viajan solos — cada estado lleva además símbolo y texto,
porque el color no puede ser el único portador de información. Ambas paletas
cumplen WCAG AA: 4.5:1 para el texto sobre cada capa, 3:1 para foco y
`borde_control`; `tests/test_accesibilidad.py` lo mide.
"""
from __future__ import annotations

from collections.abc import Iterable

# --- Paletas: dark / light ------------------------------------------------
# Única fuente de verdad del color. `aplicar_tema()` vuelca la paleta elegida
# a los atributos de módulo; el resto del código lee `es.FONDO`, `es.TEXTO`, …
TEMA_DEFECTO = "dark"
TEMAS_VALIDOS = frozenset({"dark", "light"})

PALETAS: dict[str, dict[str, str]] = {
    "dark": {
        # --- Capas: obsidiana profunda -----------------------------------
        # Los tres hex base de la identidad: `fondo` es la obsidiana del
        # altiplano, `superficie` la piedra nocturna de los paneles y
        # `superficie_alta` el campo elevado (historial, entradas).
        "fondo": "#0D1117",           # Obsidiana Profunda
        "superficie": "#161C24",      # Piedra Nocturna (paneles)
        "superficie_alta": "#1C2430", # campo elevado
        # --- Divisorias y controles ---------------------------------------
        "borde": "#2D3748",           # Estuco Sombra (divisoria sutil)
        # WCAG 1.4.11 exige 3:1 a los bordes de elementos accionables; el
        # estuco de `borde` es tenue por diseño, así que los controles usan un
        # gris piedra más claro que sí cumple sobre las tres capas.
        "borde_control": "#60708C",
        "superficie_activa": "#232E3D",  # hover obsidiana
        "foco": "#10B981",            # foco jade
        # --- Acento: el jade tallado -------------------------------------
        "acento": "#10B981",          # Verde Jade
        "acento_activo": "#34D399",   # jade iluminado (hover)
        "acento_texto": "#052E23",    # verde muy oscuro: máximo contraste
        # --- Texto -------------------------------------------------------
        "texto": "#E2E8F0",           # Blanco Ceniza
        "texto_tenue": "#94A3B8",     # Gris Epigráfico
        "seleccion": "#1E3A5F",
        # --- Señal de estado (funcional, no decorativa) ------------------
        "estado_neutro": "#94A3B8",
        "estado_proceso": "#38BDF8",
        "estado_exito": "#34D399",
        "estado_error": "#F87171",
        "estado_aviso": "#F59E0B",    # Ámbar Tunkul
        # --- Rol conversacional -----------------------------------------
        "voz_usuario": "#34D399",     # jade: el usuario
        "voz_asistente": "#F59E0B",   # ámbar tunkul: el asistente «Tukul»
    },
    "light": {
        # --- Capas: piedra al sol ----------------------------------------
        # Misma identidad en clave clara: obsidiana lavada, no blanco puro, con
        # el matiz azul frío de la piedra y contraste AA en texto y controles.
        "fondo": "#EEF1F5",
        "superficie": "#E3E8EF",
        "superficie_alta": "#F7F9FC",
        "borde": "#B4BECD",
        "borde_control": "#6E7F97",
        "superficie_activa": "#D5DCE6",
        "foco": "#047857",
        "acento": "#065F46",
        "acento_activo": "#047857",
        "acento_texto": "#FFFFFF",
        "texto": "#0D1117",
        "texto_tenue": "#41506B",
        "seleccion": "#A7D7C5",
        "estado_neutro": "#41506B",
        "estado_proceso": "#0369A1",
        "estado_exito": "#065F46",
        "estado_error": "#B42318",
        "estado_aviso": "#92400E",
        "voz_usuario": "#065F46",
        "voz_asistente": "#92400E",
    },
}

#: Paleta vigente. Los atributos de módulo (FONDO, SUPERFICIE…) se reasignan
#: desde aquí en `aplicar_tema()`.
TEMA_ACTIVO = TEMA_DEFECTO

FONDO = PALETAS[TEMA_DEFECTO]["fondo"]
SUPERFICIE = PALETAS[TEMA_DEFECTO]["superficie"]
SUPERFICIE_ALTA = PALETAS[TEMA_DEFECTO]["superficie_alta"]
BORDE = PALETAS[TEMA_DEFECTO]["borde"]
BORDE_CONTROL = PALETAS[TEMA_DEFECTO]["borde_control"]
SUPERFICIE_ACTIVA = PALETAS[TEMA_DEFECTO]["superficie_activa"]
FOCO = PALETAS[TEMA_DEFECTO]["foco"]
ACENTO = PALETAS[TEMA_DEFECTO]["acento"]
ACENTO_ACTIVO = PALETAS[TEMA_DEFECTO]["acento_activo"]
ACENTO_TEXTO = PALETAS[TEMA_DEFECTO]["acento_texto"]
#: Ámbar tunkul: acento secundario de la identidad. Marca el nombre del
#: asistente en el chat y el logotipo. Es el mismo tono que `voz_asistente`.
ACENTO_AMBAR = PALETAS[TEMA_DEFECTO]["voz_asistente"]
TEXTO = PALETAS[TEMA_DEFECTO]["texto"]
TEXTO_TENUE = PALETAS[TEMA_DEFECTO]["texto_tenue"]
SELECCION = PALETAS[TEMA_DEFECTO]["seleccion"]
ESTADO_NEUTRO = PALETAS[TEMA_DEFECTO]["estado_neutro"]
ESTADO_PROCESO = PALETAS[TEMA_DEFECTO]["estado_proceso"]
ESTADO_EXITO = PALETAS[TEMA_DEFECTO]["estado_exito"]
ESTADO_ERROR = PALETAS[TEMA_DEFECTO]["estado_error"]
ESTADO_AVISO = PALETAS[TEMA_DEFECTO]["estado_aviso"]
VOZ_USUARIO = PALETAS[TEMA_DEFECTO]["voz_usuario"]
VOZ_ASISTENTE = PALETAS[TEMA_DEFECTO]["voz_asistente"]


def tema_validado(valor: object) -> str:
    """Devuelve un tema válido; cualquier valor extraño cae en el oscuro."""
    if isinstance(valor, str) and valor in TEMAS_VALIDOS:
        return valor
    return TEMA_DEFECTO


def aplicar_tema(nombre: object) -> None:
    """Activa una paleta y reasigna los tokens de módulo (fuente única de color)."""
    global TEMA_ACTIVO, FONDO, SUPERFICIE, SUPERFICIE_ALTA, BORDE, FOCO, ACENTO
    global BORDE_CONTROL, SUPERFICIE_ACTIVA
    global ACENTO_ACTIVO, ACENTO_TEXTO, ACENTO_AMBAR, TEXTO, TEXTO_TENUE, SELECCION
    global ESTADO_NEUTRO, ESTADO_PROCESO, ESTADO_EXITO, ESTADO_ERROR, ESTADO_AVISO
    global VOZ_USUARIO, VOZ_ASISTENTE
    TEMA_ACTIVO = tema_validado(nombre)
    tokens = PALETAS[TEMA_ACTIVO]
    FONDO = tokens["fondo"]
    SUPERFICIE = tokens["superficie"]
    SUPERFICIE_ALTA = tokens["superficie_alta"]
    BORDE = tokens["borde"]
    BORDE_CONTROL = tokens["borde_control"]
    SUPERFICIE_ACTIVA = tokens["superficie_activa"]
    FOCO = tokens["foco"]
    ACENTO = tokens["acento"]
    ACENTO_ACTIVO = tokens["acento_activo"]
    ACENTO_TEXTO = tokens["acento_texto"]
    ACENTO_AMBAR = tokens["voz_asistente"]
    TEXTO = tokens["texto"]
    TEXTO_TENUE = tokens["texto_tenue"]
    SELECCION = tokens["seleccion"]
    ESTADO_NEUTRO = tokens["estado_neutro"]
    ESTADO_PROCESO = tokens["estado_proceso"]
    ESTADO_EXITO = tokens["estado_exito"]
    ESTADO_ERROR = tokens["estado_error"]
    ESTADO_AVISO = tokens["estado_aviso"]
    VOZ_USUARIO = tokens["voz_usuario"]
    VOZ_ASISTENTE = tokens["voz_asistente"]


def token(nombre: str) -> str:
    """Color de un token de la paleta vigente."""
    return PALETAS[TEMA_ACTIVO][nombre]


# --- Tipografía: tres tamaños --------------------------------------------
FAMILIA = "Inter"
#: Lista de reserva, en orden. Tk no sustituye una familia ausente por otra de
#: forma predecible: si «Inter» no está instalada cae en una fuente serif o en
#: el ancho por defecto del sistema, y toda la interfaz cambia de aspecto. Se
#: prueban primero las familias del propio proyecto y después las de escritorio
#: más comunes en Linux, macOS y Windows.
FAMILIAS_RESERVA = ("Inter", "Segoe UI", "Helvetica Neue", "Noto Sans",
                    "DejaVu Sans", "Liberation Sans", "Helvetica", "Arial")
#: Familia realmente disponible. La fija `resolver_familia()` tras crear la raíz.
_familia_activa: str | None = None
# 11 px es el mínimo legible-en-pantalla sin depender de zoom: a 10 px los
# metadatos del historial y las notas se leían con esfuerzo en pantallas 1x.
TIPO_SM = 11   # metadatos, notas al pie
TIPO_MD = 12   # controles compactos
TIPO_LG = 14   # prosa: lectura prolongada

# --- Escala (zoom) --------------------------------------------------------
# Multiplica los tres tamaños por igual: la jerarquía se conserva, solo cambia
# el cuerpo. Acotado para que un Ctrl+= o Ctrl+- no degrade la legibilidad.
ZOOM = 1.0
ZOOM_MIN = 0.8
ZOOM_MAX = 1.5
ZOOM_STEP = 0.1

# --- Espaciado: rejilla de 4 --------------------------------------------
ESP = {"xs": 4, "sm": 8, "md": 12, "lg": 16}


def resolver_familia(familias_disponibles: Iterable[str] | None = None) -> str:
    """Elige la primera familia instalada de `FAMILIAS_RESERVA`.

    Se resuelve una vez, con la raíz Tk ya creada (`tkinter.font.families()`
    necesita un intérprete). Sin información disponible se conserva `FAMILIA`.
    """
    global _familia_activa
    if familias_disponibles is None:
        _familia_activa = FAMILIA
        return FAMILIA
    disponibles = {str(nombre).lower() for nombre in familias_disponibles}
    for candidata in FAMILIAS_RESERVA:
        if candidata.lower() in disponibles:
            _familia_activa = candidata
            return candidata
    _familia_activa = FAMILIA
    return FAMILIA


def tamano_ventana(ancho: int, alto: int, pantalla_ancho: int, pantalla_alto: int,
                   *, minimo: tuple[int, int] = (480, 360)) -> str:
    """Tamaño que cabe en la pantalla del usuario, con margen para el sistema.

    Los diálogos usaban tamaños absolutos (`760x520`, `700x620`): en un portátil
    de 1366x768 el de configuración quedaba más alto que la pantalla y sus
    botones de acción, fuera de alcance. Se conserva el tamaño preferido cuando
    cabe, y el mínimo se aplica solo si la pantalla lo permite.
    """
    disponible_ancho, disponible_alto = pantalla_ancho - 32, pantalla_alto - 64
    if disponible_ancho <= 0 or disponible_alto <= 0:
        return f"{ancho}x{alto}"
    minimo_ancho, minimo_alto = minimo
    return (f"{max(min(ancho, disponible_ancho), min(minimo_ancho, disponible_ancho))}"
            f"x{max(min(alto, disponible_alto), min(minimo_alto, disponible_alto))}")


def fuente(tamano: int = TIPO_MD, *, negrita: bool = False, cursiva: bool = False) -> tuple:
    """Construye una fuente de la escala. Evita tamaños sueltos por el código."""
    estilos = []
    if negrita:
        estilos.append("bold")
    if cursiva:
        estilos.append("italic")
    cuerpo = max(1, round(tamano * ZOOM))
    return (_familia_activa or FAMILIA, cuerpo, *estilos)


def _canal(valor: int) -> float:
    """Linealiza un canal sRGB de 0-255 para el cálculo de luminancia."""
    proporcion = valor / 255
    return proporcion / 12.92 if proporcion <= 0.04045 else ((proporcion + 0.055) / 1.055) ** 2.4


def luminancia(color: str) -> float:
    """Luminancia relativa de un color «#rrggbb» según WCAG 2.1."""
    color = color.lstrip("#")
    rojo, verde, azul = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _canal(rojo) + 0.7152 * _canal(verde) + 0.0722 * _canal(azul)


def contraste(primero: str, segundo: str) -> float:
    """Razón de contraste WCAG entre dos colores (1:1 a 21:1)."""
    a, b = luminancia(primero), luminancia(segundo)
    claro, oscuro = max(a, b), min(a, b)
    return (claro + 0.05) / (oscuro + 0.05)
