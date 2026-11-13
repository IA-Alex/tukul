from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from tukul_ui import estilo as es
from tukul_ui.tooltip import ToolTip

if TYPE_CHECKING:  # evita el import circular: app importa TopBar
    from tukul_ui.app import TukulApp


class TopBar(ttk.Frame):
    """Barra superior partida en tres zonas.

    Antes era una fila plana donde todo pesaba lo mismo y el nombre del
    documento quedaba emparedado entre controles. Ahora:

    - **izquierda**: las acciones sobre el archivo (Menú, Guardar);
    - **centro**: si hay cambios sin guardar y qué artículo está abierto;
    - **derecha**: el contexto y la configuración (Modelo, Tema, Panel).

    La zona derecha empieza tras un separador fino, así que la vista lee
    «esto es lo que hago» y luego «así está configurado», sin mezclarlas.

    Cuando la ventana se estrecha no desaparece todo por igual: primero cede
    el estado del documento y luego se recorta el nombre, porque saber qué se
    está editando importa más que saber que no hay cambios pendientes.
    """

    TEXTO_SIN_DOCUMENTO = "Sin artículo abierto"
    #: Lado del logotipo en píxeles. Coincide con los 24x24 del SVG original.
    LOGO = 24
    # Ancho máximo del chip de modelo, en píxeles. La barra pide espacio antes
    # de saber qué píxel le toca a cada fuente y el nombre del modelo crece
    # con cada perfil: medido en caracteres, un id largo seguía desbordando.
    ANCHO_MODELO = 140
    # Por debajo de este ancho de ventana el estado del documento se retira
    # para dejar sitio al nombre del artículo (ver `_ajustar_por_ancho`).
    ANCHO_ESTADO = 1080
    # Ancho máximo del nombre del artículo, en píxeles. El recorte era por
    # caracteres (`nombre[:41]`): con una fuente ancha o con zoom, 41 caracteres
    # desbordaban, y con una estrecha se perdía nombre que cabía. Se mide con la
    # fuente real, igual que el chip de modelo.
    ANCHO_DOCUMENTO = 420

    def __init__(self, parent: tk.Misc, callbacks: dict[str, Callable], menu: tk.Menu, state: Any, theme: str, **kwargs) -> None:
        super().__init__(parent, style="Cabecera.TFrame",
                         padding=(es.ESP["md"], es.ESP["sm"], es.ESP["md"], es.ESP["sm"]), **kwargs)
        self.callbacks = callbacks
        self.menu = menu
        # La barra consulta el perfil activo de la app: `state` es la propia
        # aplicación, no un widget genérico (sin tipar, mypy confundía
        # `state.profile` con el `pack_slaves` heredado de Tk).
        self.app: TukulApp = state
        self.theme = theme
        self._build()

    def _build(self) -> None:
        # Tres columnas con pesos explícitos. `pack` repartía por orden y, al
        # no caber, dejaba el nombre del documento con cero píxeles mientras
        # el resto conservaba su ancho: la información más importante era la
        # primera en desaparecer. Con `grid` el centro cede proporcionalmente.
        self.columnconfigure(0, weight=0)   # acciones
        self.columnconfigure(1, weight=1, minsize=150)   # documento (cede, pero nunca a cero)
        self.columnconfigure(2, weight=0)   # configuración
        self.rowconfigure(0, weight=1)

        # --- Zona izquierda: marca y acciones sobre el archivo -----------
        self.zona_izquierda = ttk.Frame(self, style="Cabecera.TFrame")
        self.zona_izquierda.grid(row=0, column=0, sticky="nsw")

        # --- Logotipo: bloque maya/tunkul --------------------------------
        # Va antes del menú para que la barra se lea «marca → acciones». El
        # dibujo es un `Canvas` que reproduce el SVG del logo con los tokens
        # del tema: se repinta en `_pintar_logo` al cambiar de tema, así que no
        # guarda colores congelados.
        self.logo = tk.Canvas(self.zona_izquierda, width=self.LOGO, height=self.LOGO,
                              highlightthickness=0, borderwidth=0,
                              background=es.FONDO)
        self.logo.pack(side="left", padx=(0, es.ESP["xs"]))
        self._pintar_logo()

        self.logo_label = ttk.Label(self.zona_izquierda, text="Tukul",
                                    style="Marca.TLabel")
        self.logo_label.pack(side="left", padx=(0, es.ESP["sm"]))
        ToolTip(self.logo_label, "Tukul, editor conversacional")

        # Ancho fijo: en `clam` el Menubutton se estira hasta el ancho de su
        # desplegable, así que aunque el texto sea solo «☰» medía 149 px y se
        # comía el hueco del nombre del documento. El menú no es estrecho ni
        # ancho por su contenido: el botón es un icono con tooltip.
        self.boton_menu = ttk.Menubutton(self.zona_izquierda, text="☰", menu=self.menu, width=2)
        self.boton_menu.pack(side="left")

        self.boton_guardar = ttk.Button(self.zona_izquierda, text="Guardar", style="Guardar.TButton", command=self.callbacks["save"])
        self.boton_guardar.pack(side="left", padx=(es.ESP["sm"], 0))
        # «Guardar» depende de un documento y de Ctrl+S: fuera del recorrido
        # con Tab para que este empiece por Menú (navegación, nunca destructiva)
        # y no por una acción que aparece pesada pero no aplica aún.
        self.boton_guardar.configure(takefocus=False)
        self.boton_guardar.configure(cursor="hand2")

        # --- Zona derecha: configuración y contexto ----------------------
        self.zona_derecha = ttk.Frame(self, style="Cabecera.TFrame")
        self.zona_derecha.grid(row=0, column=2, sticky="nse")

        self.boton_panel = ttk.Button(self.zona_derecha, text="◧  Panel IA  (F6)", command=self.callbacks["toggle_asistente"])
        self.boton_panel.pack(side="right", padx=(es.ESP["xs"], 0))

        self.boton_tema = ttk.Button(self.zona_derecha, style="Plana.TButton", command=self.callbacks["cambiar_tema"])
        self.boton_tema.pack(side="right", padx=(0, es.ESP["xs"]))

        self.profile_chip = ttk.Button(self.zona_derecha, text=self._texto_modelo(), style="Plana.TButton", command=self.callbacks["settings"])
        self.profile_chip.pack(side="right", padx=(0, es.ESP["xs"]))

        # Separador: marca dónde acaban las acciones de trabajo y empieza la
        # configuración. Es divisoria, no pieza accionable, por eso usa el
        # borde sutil y no `BORDE_CONTROL`.
        self.separador = ttk.Separator(self.zona_derecha, orient="vertical", style="Cabecera.TSeparator")
        self.separador.pack(side="right", fill="y", pady=es.ESP["sm"], padx=(es.ESP["sm"], es.ESP["xs"]))

        self.references_button = ttk.Button(self.zona_derecha, text="Contexto: 0", style="Plana.TButton", command=self.callbacks["manage_references"])
        self.references_button.pack(side="right")

        # --- Zona central: estado del guardado y documento activo --------
        # Ambos viven en una sub-columna propia para que `grid` trate el
        # centro como una sola pieza (si el documento fuera una celda aparte,
        # el estado quedaría flotando entre él y las acciones).
        self.zona_centro = ttk.Frame(self, style="Cabecera.TFrame")
        self.zona_centro.grid(row=0, column=1, sticky="ew")
        self.zona_centro.columnconfigure(1, weight=1)

        # Estado del guardado: etiqueta, nunca botón. Va antes que el
        # documento: describe lo mismo (qué hay abierto) y así deja de leerse
        # como un control apagado junto a uno accionable.
        self.sync_label = ttk.Label(self.zona_centro, text="◌  Sin cambios", style="Cabecera.TLabel")
        self.sync_label.grid(row=0, column=0, sticky="w", padx=(es.ESP["md"], 0))

        # Nombre del artículo. La ventana solo dice «Tukul»: con dos o tres
        # artículos abiertos en el día no había forma de saber cuál está activo
        # sin leer el historial. Se recorta, nunca se desborda ni empuja a los
        # controles de la derecha. Sin documento muestra el hueco explícito en
        # vez de dejar un vacío que parecía un fallo de carga.
        self.documento_var = tk.StringVar(value=self.TEXTO_SIN_DOCUMENTO)
        self.documento_label = ttk.Label(self.zona_centro, textvariable=self.documento_var,
                                         style="Cabecera.TLabel", anchor="w")
        self.documento_label.grid(row=0, column=1, sticky="ew", padx=(es.ESP["sm"], es.ESP["sm"]))
        ToolTip(self.documento_label, "Documento activo")

        self.boton_menu.configure(cursor="hand2")

        ToolTip(self.boton_menu, "Archivo: abrir, guardar y proyectos")
        ToolTip(self.boton_guardar, "Guardar el artículo (Ctrl+S)")
        ToolTip(self.references_button, "Gestionar los artículos de contexto")
        self.tooltip_panel = ToolTip(self.boton_panel, "Mostrar u ocultar el panel IA (F6)")
        self.tooltip_tema = ToolTip(self.boton_tema, "Cambiar de tema claro/oscuro")
        self.tooltip_modelo = ToolTip(self.profile_chip, self._tooltip_modelo())

        self.actualizar_estado(self.theme)
        self.winfo_toplevel().bind("<Configure>", self._ajustar_por_ancho, add="+")
        self.after_idle(lambda: self._ajustar_por_ancho())

    def _pintar_logo(self) -> None:
        """Dibuja el isotipo de Tukul con los tokens del tema.

        Es la versión compacta (24 px) del logotipo `docs/assets/tukul-logo.svg`:
        el círculo de piedra nocturna con borde de estuco, y dentro la lengüeta
        verde jade (el libro/lengüeta que sube). Se limpia y repinta en cada
        cambio de tema para no congelar colores.
        """
        self.logo.delete("all")
        lado = self.LOGO
        c = lado / 2
        self.logo.configure(background=es.FONDO)
        # Círculo base: piedra nocturna sobre obsidiana, borde de estuco.
        self.logo.create_oval(
            1, 1, lado - 1, lado - 1, fill=es.SUPERFICIE,
            outline=es.BORDE, width=1,
        )
        # Lengüeta jade: la forma que sube (libro/ala), en el acento.
        self.logo.create_polygon(
            c, lado - 4,          # base del centro
            c - 1, c + 1,         # cintura izquierda
            c - 6, c - 4,         # ala izquierda
            c, c - 8,             # punta superior izquierda
            c + 6, c - 4,         # ala derecha
            c + 1, c + 1,         # cintura derecha
            fill=es.ACENTO, outline="",
        )

    def actualizar_tema(self) -> None:
        """Repinta las piezas con color directo (el logo es un `Canvas`)."""
        self._pintar_logo()

    def _ajustar_por_ancho(self, evento: tk.Event | None = None) -> None:
        """Con la barra estrecha, cede primero el estado, nunca el documento.

        «Sin cambios» es el estado por defecto y no aporta nada que el nombre
        no diga; el nombre, en cambio, es lo único que responde «qué tengo
        abierto». Cuando no caben los dos, se queda el nombre. El estado sigue
        disponible en la barra de estado inferior.
        """
        ancho = evento.width if evento is not None and evento.widget is self.winfo_toplevel() else self.winfo_width()
        if ancho <= 1:  # todavía sin geometría: no se decide nada
            return
        if ancho < self.ANCHO_ESTADO:
            self.sync_label.grid_remove()
        else:
            self.sync_label.grid()

    def _texto_modelo(self) -> str:
        """Nombre del modelo, recortado por píxeles para que el chip no crezca.

        Se mide con la fuente real del estilo, no contando caracteres: «Modelo:
        » en sí ya ocupa ancho, y un modelo con letras anchas no cabe aunque
        tenga pocos caracteres. El nombre completo va en el tooltip.
        """
        modelo = self.app.profile.model or "sin configurar"
        prefijo = "Modelo: "
        texto = f"{prefijo}{modelo}"
        fuente = tkfont.Font(font=es.fuente(es.TIPO_SM))
        if fuente.measure(texto) <= self.ANCHO_MODELO:
            return texto
        recorte = modelo
        while recorte and fuente.measure(f"{prefijo}{recorte}…") > self.ANCHO_MODELO:
            recorte = recorte[:-1]
        return f"{prefijo}{recorte}…"

    def _tooltip_modelo(self) -> str:
        modelo = self.app.profile.model or "sin configurar"
        return f"Modelo activo: {modelo}. Cambiar de perfil"

    def actualizar_modelo(self) -> None:
        """Reaplica el chip tras cambiar de perfil, sin recrear el widget."""
        self.profile_chip.config(text=self._texto_modelo())
        self.tooltip_modelo.set_texto(self._tooltip_modelo())

    def _nombre_recortado(self, nombre: str) -> str:
        """Recorta el nombre por píxeles, no por número de caracteres."""
        ancho = self.documento_label.winfo_width() if self.documento_label.winfo_ismapped() else 0
        limite = ancho if ancho > 1 else self.ANCHO_DOCUMENTO
        fuente = tkfont.Font(font=es.fuente(es.TIPO_SM))
        if fuente.measure(nombre) <= limite:
            return nombre
        recorte = nombre
        while recorte and fuente.measure(f"{recorte}…") > limite:
            recorte = recorte[:-1]
        return f"{recorte}…" if recorte else nombre

    def actualizar_documento(self, nombre: str | None) -> None:
        """Muestra el artículo activo; sin documento, lo dice en vez de callar."""
        if not nombre:
            self.documento_var.set(self.TEXTO_SIN_DOCUMENTO)
            return
        self.documento_var.set(self._nombre_recortado(nombre))

    def actualizar_estado(self, theme: str) -> None:
        """El botón anuncia el tema al que se irá; el actual se ve en pantalla."""
        self.theme = theme
        if self.theme == "light":
            etiqueta = "☾  Oscuro"
            tooltip = "Cambiar a tema oscuro (actual: claro)"
        else:
            etiqueta = "☀  Claro"
            tooltip = "Cambiar a tema claro (actual: oscuro)"
        self.boton_tema.config(text=etiqueta)
        self.tooltip_tema.set_texto(tooltip)
