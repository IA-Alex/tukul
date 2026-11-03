"""Sistema visual de Tukul: precisión, estructura y foco.

Reglas del sistema, deliberadamente estrechas para que la interfaz se lea como
una sola pieza:

- **Dos paletas completas** (`dark`, `light`), centralizadas en `PALETAS`. Los
  atributos de módulo (`FONDO`, `SUPERFICIE`…) son SIEMPRE los del tema activo:
  `aplicar_tema()` los reasigna en bloque, así que no hay segunda fuente de
  verdad ni copias congeladas del color.
- **Un fondo** (`fondo`) y **dos superficies** (`superficie`, `superficie_alta`).
  Nada más. La profundidad se expresa con esas tres capas y con el borde.
- **Un acento** (`acento`), reservado para la acción primaria y la identidad.
- **Escala tipográfica de tres tamaños**: `TIPO_SM`, `TIPO_MD`, `TIPO_LG`.
- **Espaciado de 4/8/12/16** (`ESP`). Ningún margen fuera de esa rejilla.

Los colores de estado (`ESTADO_*`) NO son acentos: son señal funcional,
desaturada, y nunca viajan solas — cada estado lleva además símbolo y texto,
porque el color no puede ser el único portador de información. Ambas paletas
cumplen WCAG AA (4.5:1 para texto normal y 3:1 para el foco) contra las tres
capas.
"""
from __future__ import annotations

# --- Paletas: dark / light ------------------------------------------------
# Única fuente de verdad del color. `aplicar_tema()` vuelca la paleta elegida
# a los atributos de módulo; el resto del código lee `es.FONDO`, `es.TEXTO`, …
TEMA_DEFECTO = "dark"
TEMAS_VALIDOS = frozenset({"dark", "light"})

PALETAS: dict[str, dict[str, str]] = {
    "dark": {
        # --- Capas ------------------------------------------------------
        "fondo": "#18181B",           # grafito de la aplicación
        "superficie": "#2C2C30",      # paneles: separación sobria
        "superficie_alta": "#37373C", # campos, conversación y elementos activos
        "borde": "#62626F",           # divisores discretos
        # El indicador de foco sí es información necesaria: WCAG 1.4.11 exige
        # 3:1 contra el fondo adyacente. Verificado contra las tres capas
        # (6.2:1 en el peor caso).
        "foco": "#9DBBFF",
        # --- Acento (uno) ----------------------------------------------
        "acento": "#7AA7FF",          # cobalto: actividad y acciones de IA
        "acento_activo": "#A5C4FF",
        "acento_texto": "#10131A",    # texto sobre el acento
        # --- Texto -----------------------------------------------------
        "texto": "#F4F4F5",
        "texto_tenue": "#C7C7CC",
        "seleccion": "#3A5182",
        # --- Señal de estado (funcional, no decorativa) ----------------
        "estado_neutro": "#A4A4AD",
        "estado_proceso": "#7FD6E0",
        "estado_exito": "#8DE2B6",
        "estado_error": "#E28D8D",
        "estado_aviso": "#E2C88D",
        # --- Rol conversacional ---------------------------------------
        "voz_usuario": "#9FD0C9",
        "voz_asistente": "#D4B5FF",
    },
    "light": {
        "fondo": "#F4F4F5",
        "superficie": "#E4E4E7",
        "superficie_alta": "#FAFAFA",
        "borde": "#A1A1AA",
        "foco": "#1D4ED8",
        "acento": "#1D4ED8",
        "acento_activo": "#1E40AF",
        "acento_texto": "#FFFFFF",
        "texto": "#18181B",
        "texto_tenue": "#3F3F46",
        "seleccion": "#B7C9FF",
        "estado_neutro": "#52525B",
        "estado_proceso": "#155E75",
        "estado_exito": "#166534",
        "estado_error": "#B91C1C",
        "estado_aviso": "#92400E",
        "voz_usuario": "#115E59",
        "voz_asistente": "#6D28D9",
    },
}

#: Paleta vigente. Los atributos de módulo (FONDO, SUPERFICIE…) se reasignan
#: desde aquí en `aplicar_tema()`.
TEMA_ACTIVO = TEMA_DEFECTO

FONDO = PALETAS[TEMA_DEFECTO]["fondo"]
SUPERFICIE = PALETAS[TEMA_DEFECTO]["superficie"]
SUPERFICIE_ALTA = PALETAS[TEMA_DEFECTO]["superficie_alta"]
BORDE = PALETAS[TEMA_DEFECTO]["borde"]
FOCO = PALETAS[TEMA_DEFECTO]["foco"]
ACENTO = PALETAS[TEMA_DEFECTO]["acento"]
ACENTO_ACTIVO = PALETAS[TEMA_DEFECTO]["acento_activo"]
ACENTO_TEXTO = PALETAS[TEMA_DEFECTO]["acento_texto"]
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
    global ACENTO_ACTIVO, ACENTO_TEXTO, TEXTO, TEXTO_TENUE, SELECCION
    global ESTADO_NEUTRO, ESTADO_PROCESO, ESTADO_EXITO, ESTADO_ERROR, ESTADO_AVISO
    global VOZ_USUARIO, VOZ_ASISTENTE
    TEMA_ACTIVO = tema_validado(nombre)
    tokens = PALETAS[TEMA_ACTIVO]
    FONDO = tokens["fondo"]
    SUPERFICIE = tokens["superficie"]
    SUPERFICIE_ALTA = tokens["superficie_alta"]
    BORDE = tokens["borde"]
    FOCO = tokens["foco"]
    ACENTO = tokens["acento"]
    ACENTO_ACTIVO = tokens["acento_activo"]
    ACENTO_TEXTO = tokens["acento_texto"]
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


def colores() -> dict[str, str]:
    """Vista plana del tema activo con los nombres históricos de `app.COLORS`.

    Compatibilidad para quien consumía el diccionario estático: la fuente única
    de verdad sigue siendo `PALETAS` y esta función devuelve SIEMPRE los tokens
    del tema vigente, nunca una copia congelada del anterior.
    """
    t = PALETAS[TEMA_ACTIVO]
    return {
        "bg": t["fondo"], "panel": t["superficie"], "raised": t["superficie_alta"],
        "field": t["superficie_alta"], "text": t["texto"], "muted": t["texto_tenue"],
        "muted_light": t["texto_tenue"], "accent": t["acento"],
        "accent_text": t["acento_texto"], "border": t["borde"],
        "selection": t["seleccion"], "assistant": t["voz_asistente"],
    }


# --- Tipografía: tres tamaños --------------------------------------------
FAMILIA = "Inter"
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


def fuente(tamano: int = TIPO_MD, *, negrita: bool = False, cursiva: bool = False) -> tuple:
    """Construye una fuente de la escala. Evita tamaños sueltos por el código."""
    estilos = []
    if negrita:
        estilos.append("bold")
    if cursiva:
        estilos.append("italic")
    cuerpo = max(1, round(tamano * ZOOM))
    return (FAMILIA, cuerpo, *estilos)


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
