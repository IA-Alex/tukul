"""Sistema visual de Articulador: fuente única de color, tipografía y espaciado.

Reglas del sistema, deliberadamente estrechas para que la interfaz se lea como
una sola pieza:

- **Un fondo** (`FONDO`) y **dos superficies** (`SUPERFICIE`, `SUPERFICIE_ALTA`).
  Nada más. La profundidad se expresa con esas tres capas y con el borde.
- **Un acento** (`ACENTO`), reservado para la acción primaria y la identidad.
- **Escala tipográfica de tres tamaños**: `TIPO_SM`, `TIPO_MD`, `TIPO_LG`.
- **Espaciado de 4/8/12/16** (`ESP`). Ningún margen fuera de esa rejilla.

Los colores de estado (`ESTADO_*`) NO son acentos: son señal funcional,
desaturada, y nunca viajan solas — cada estado lleva además símbolo y texto,
porque el color no puede ser el único portador de información.
"""
from __future__ import annotations

# --- Capas ---------------------------------------------------------------
FONDO = "#12171d"           # lienzo de la ventana
SUPERFICIE = "#1a2129"      # paneles y contenedores
SUPERFICIE_ALTA = "#232e38" # campos, elementos elevados, filas activas
BORDE = "#3f4f5c"           # separación decorativa entre capas
# El indicador de foco sí es información necesaria: WCAG 1.4.11 exige 3:1 contra
# el fondo adyacente. Verificado contra las tres capas (6.4:1 en el peor caso).
FOCO = "#8fa6b5"

# --- Acento (uno) --------------------------------------------------------
ACENTO = "#69c7b2"
ACENTO_ACTIVO = "#8cdbc8"
ACENTO_TEXTO = "#08201c"    # texto sobre el acento

# --- Texto ---------------------------------------------------------------
TEXTO = "#e9eff3"
TEXTO_TENUE = "#a8bac6"
SELECCION = "#33606b"

# --- Señal de estado (funcional, no decorativa) --------------------------
ESTADO_NEUTRO = "#a8bac6"
ESTADO_PROCESO = "#7fb6d9"
ESTADO_EXITO = "#69c7b2"
ESTADO_ERROR = "#e79080"
ESTADO_AVISO = "#d8b878"

# --- Rol conversacional --------------------------------------------------
VOZ_USUARIO = "#69c7b2"
VOZ_ASISTENTE = "#c9b3ff"

# --- Tipografía: tres tamaños --------------------------------------------
FAMILIA = "DejaVu Sans"
TIPO_SM = 9    # metadatos, notas al pie
TIPO_MD = 10   # cuerpo de interfaz
TIPO_LG = 13   # el artículo, que es el foco

# --- Espaciado: rejilla de 4 --------------------------------------------
ESP = {"xs": 4, "sm": 8, "md": 12, "lg": 16}


def fuente(tamano: int = TIPO_MD, *, negrita: bool = False, cursiva: bool = False) -> tuple:
    """Construye una fuente de la escala. Evita tamaños sueltos por el código."""
    estilos = []
    if negrita:
        estilos.append("bold")
    if cursiva:
        estilos.append("italic")
    return (FAMILIA, tamano, *estilos)


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
