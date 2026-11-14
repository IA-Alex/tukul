"""Ventana/DPI/geometría/tema de la aplicación, en un solo lugar.

Extraído de `TukulApp` (DF-001, ADR-0005 paso 2). La ventana mezclaba el ciclo
de vida del documento y del LLM con detalles de presentación del sistema
operativo: declararse DPI-aware, calcular un tamaño inicial, restaurar la
geometría guardada (que puede venir de otro monitor) y validar el tema. Nada de
eso conoce los widgets de la aplicación; todo depende solo de la raíz Tk y del
estado persistido.

`WindowShell` es dueño del estado de presentación (`theme`) y del acceso a Tk
para esas cuatro cosas. La lógica pura de saneado sigue en `tukul_ui.ventana`
(probada sin montar la ventana) y aquí solo se reexpone para que el host tenga
un punto único: `TukulApp` conserva sus delegaciones históricas para no romper a
los consumidores ni a los tests.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping

from tukul_ui import estilo as es
from tukul_ui import tema as _tema
from tukul_ui import ventana

#: Ancho/alto por defecto cuando la pantalla no reporta dimensiones creíbles.
ANCHO_DEFECTO = 1180
ALTO_DEFECTO = 760
#: Fracción de la pantalla que ocupa la ventana al abrir, con topes absolutos.
FRACCION_PANTALLA = 0.8
ANCHO_TOPE = 1400
ALTO_TOPE = 900
#: Por debajo de estas dimensiones no se confía en el sondeo de pantalla.
PANTALLA_MINIMA = 100


class WindowShell:
    """DPI, tamaño inicial, geometría guardada y tema de la ventana raíz.

    El host es la propia raíz Tk (o cualquier objeto que responda a
    `geometry`/`winfo_screenwidth`/`tk`); el único estado propio es el tema
    activo, que se inicializa validando el valor persistido.
    """

    PATRON_GEOMETRIA = ventana.PATRON_GEOMETRIA

    def __init__(self, host: tk.Tk) -> None:
        self._host = host
        # El estado persistido se lee del host en el momento (no se guarda una
        # copia): así una restauración posterior a una recarga del estado no
        # trabaja sobre datos congelados del arranque.
        # Orden del original: primero DPI/escala, y solo entonces el zoom y el
        # tema (que dependen de la escala ya fijada).
        self.ajustar_dpi()
        # El zoom se aplica sobre el módulo de estilo (estado global del
        # sistema visual) porque las fuentes deben nacer escaladas.
        es.ZOOM = self.zoom_validado(self._estado_guardado("zoom"))
        self.theme = self.tema_validado(self._estado_guardado("theme"))

    # ─── Saneadores (delegan en `tukul_ui.ventana`, lógica pura) ─────────────

    @classmethod
    def geometria_saneada(cls, guardada: object, pantalla_ancho: int,
                          pantalla_alto: int) -> str | None:
        """Normaliza y acota una geometría; None si no es utilizable."""
        return ventana.geometria_saneada(guardada, pantalla_ancho, pantalla_alto)

    @staticmethod
    def zoom_validado(valor: object) -> float:
        """Convierte el zoom persistido a un factor acotado; 1.0 ante basura."""
        return ventana.zoom_validado(valor)

    @staticmethod
    def recientes_validados(valor: object) -> list[str]:
        """Filtra la lista de recientes persistida a rutas útiles, con tope."""
        return ventana.recientes_validados(valor)

    @staticmethod
    def tema_validado(valor: object) -> str:
        """Convierte el tema persistido a uno válido; 'dark' ante basura."""
        return es.tema_validado(valor)

    # ─── DPI ────────────────────────────────────────────────────────────────

    def ajustar_dpi(self) -> None:
        """Declara la aplicación «DPI-aware» y calibra la escala de Tk.

        Sin esto, en Windows con escalado al 150-200 % el sistema reescala una
        ventana dibujada a 96 DPI: texto borroso y controles de tamaño
        incorrecto. En X11 se consulta el DPI del servidor para que `tk scaling`
        coincida con la pantalla real. Todo es best-effort: sondeos de entornos
        sin el módulo, sin soporte o con servidores que ya lo resuelven.
        """
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except (ImportError, AttributeError, OSError):
            pass
        try:
            pulgadas = float(self._host.winfo_fpixels("1i"))
            if pulgadas > 0:
                self._host.tk.call("tk", "scaling", pulgadas / 72.0)
        except (tk.TclError, ValueError):
            pass
        # La familia tipográfica se resuelve con la raíz ya viva.
        try:
            from tkinter import font as tkfont

            es.resolver_familia(tkfont.families(self._host))
        except tk.TclError:
            pass

    # ─── Geometría ──────────────────────────────────────────────────────────

    def aplicar_tamano_inicial(self) -> None:
        """Propone un tamaño inicial acorde a la pantalla. Se aplica una sola vez.

        Cualquier `geometry()` posterior —del usuario, de una restauración de
        sesión o de quien integre la aplicación— manda, porque aquí no hay
        ninguna reprogramación que lo pise después.
        """
        ancho_pantalla = self._host.winfo_screenwidth()
        alto_pantalla = self._host.winfo_screenheight()
        if ancho_pantalla > PANTALLA_MINIMA and alto_pantalla > PANTALLA_MINIMA:
            ancho = min(int(ancho_pantalla * FRACCION_PANTALLA), ANCHO_TOPE)
            alto = min(int(alto_pantalla * FRACCION_PANTALLA), ALTO_TOPE)
            self._host.minsize(min(ventana.ANCHO_MINIMO_VENTANA, ancho),
                               min(ventana.ALTO_MINIMO_VENTANA, alto))
            self._host.geometry(f"{ancho}x{alto}")
        else:
            self._host.minsize(ventana.ANCHO_MINIMO_VENTANA, ventana.ALTO_MINIMO_VENTANA)
            self._host.geometry(f"{ANCHO_DEFECTO}x{ALTO_DEFECTO}")

    def ventana_mapeada(self) -> bool:
        """¿La ventana ya tiene tamaño y posición reales?

        Antes de `update_idletasks`, `geometry()` devuelve el tamaño pedido
        (a menudo «1x1+0+0»), no el real. Persistir ese valor convertiría una
        ventana que aún no se pintó en una miniatura de 1120x540 al reabrir.
        """
        try:
            return bool(self._host.winfo_ismapped() and self._host.winfo_width() > 1
                        and self._host.winfo_height() > 1)
        except tk.TclError:
            return False

    def restaurar_geometria(self) -> None:
        """Restaura la geometría sin permitir que la ventana desaparezca.

        Una geometría guardada puede venir de otro monitor, de un cambio de
        resolución o de una sesión remota. Tk acepta esos valores sin error,
        pero el resultado puede dejar controles esenciales fuera del viewport.
        Se conserva el tamaño/posición cuando caben y se corrigen de forma
        defensiva cuando no.
        """
        guardada = self._estado_guardado("geometry")
        if not isinstance(guardada, str) or not guardada.strip():
            return

        ancho, alto = self._host.winfo_screenwidth(), self._host.winfo_screenheight()
        if ancho <= PANTALLA_MINIMA or alto <= PANTALLA_MINIMA:
            return
        saneada = self.geometria_saneada(guardada, ancho, alto)
        if saneada is not None:
            self._host.geometry(saneada)

    def saneada_actual(self) -> str | None:
        """Geometría viva de la ventana, normalizada; None si no es utilizable.

        No decide si conviene persistirla (eso es política del host: una ventana
        aún no mapeada devuelve su tamaño pedido, p. ej. «1x1+0+0»); solo mide,
        sanea y devuelve.
        """
        return self.geometria_saneada(self._host.geometry(),
                                      self._host.winfo_screenwidth(),
                                      self._host.winfo_screenheight())

    # ─── Tema ───────────────────────────────────────────────────────────────

    def aplicar_theme(self, reaplicar_widgets: Callable[[], None]) -> None:
        """Aplica el sistema visual del tema activo.

        Los estilos ttk se repintan en bloque (`tukul_ui.tema`); los widgets Tk
        con colores directos los repinta `reaplicar_widgets`, que aporta el host
        porque es quien conoce sus widgets. No se destruye ni recrea nada.
        """
        _tema.aplicar_estilos(self._host, self.theme, reaplicar_widgets)

    def fijar_tema(self, nombre: object) -> str:
        """Valida y fija el tema activo; devuelve el nombre efectivo."""
        self.theme = self.tema_validado(nombre)
        return self.theme

    # ─── Interno ────────────────────────────────────────────────────────────

    def _estado_guardado(self, clave: str) -> object:
        """Lee una clave del estado persistido VIVO del host (no una copia)."""
        estado = getattr(self._host, "ui_state", None)
        if not isinstance(estado, Mapping):
            return None
        return estado.get(clave)
