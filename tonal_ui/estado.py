"""Estados visibles de la interfaz durante una consulta.

Antes, cada punto del flujo escribía a mano una cadena distinta en la etiqueta
de actividad ("Mensaje recibido…", "Revisa conexión…", "Envío cancelado."). No
había forma de saber en qué estado estaba la aplicación ni de probarlo: el
estado existía solo como texto suelto.

Aquí cada estado es un dato con tres portadores independientes:

- **símbolo**: distingue el estado sin depender del color (daltonismo, capturas
  en escala de grises, temas de alto contraste).
- **texto**: explica en lenguaje llano qué está ocurriendo, sin documentación.
- **color**: refuerza, nunca informa en solitario.

Además `descripcion_accesible` alimenta el nombre accesible del indicador, de
modo que un lector de pantalla anuncie el cambio aunque no vea ni símbolo ni
color.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from articulador_ui import estilo


@dataclass(frozen=True)
class Estado:
    """Presentación de un estado de la conversación.

    `token` nombra el color en la paleta activa (`estilo.token`): el valor real
    se resuelve al consultarlo, de modo que un cambio de tema se refleja al
    instante sin reconstruir ni los estados ni la ventana.
    """

    clave: str
    simbolo: str
    titulo: str
    ayuda: str
    token: str

    def descripcion_accesible(self, detalle: str = "") -> str:
        """Texto para lectores de pantalla: estado, explicación y detalle."""
        partes = [f"Estado: {self.titulo}", self.ayuda]
        if detalle:
            partes.append(detalle)
        return ". ".join(parte.rstrip(".") for parte in partes if parte) + "."


class EstadoUI(Enum):
    """Los seis estados que la interfaz debe saber explicar."""

    REPOSO = Estado(
        "reposo", "○", "En reposo",
        "Escribe un mensaje y pulsa Enviar",
        "estado_neutro",
    )
    PREPARANDO = Estado(
        "preparando", "◐", "Preparando contexto",
        "Buscando en tus artículos locales lo relevante para la consulta",
        "estado_proceso",
    )
    TRANSMITIENDO = Estado(
        "transmitiendo", "◉", "Recibiendo respuesta",
        "El modelo está escribiendo; puedes cancelar en cualquier momento",
        "acento",
    )
    EXITO = Estado(
        "exito", "✓", "Respuesta completa",
        "La respuesta llegó entera",
        "estado_exito",
    )
    ERROR = Estado(
        "error", "✕", "No se pudo completar",
        "Revisa la conexión, el modelo o los límites del perfil",
        "estado_error",
    )
    CANCELADO = Estado(
        "cancelado", "⊘", "Cancelado",
        "Se descartará la respuesta que llegue tarde",
        "estado_aviso",
    )

    @property
    def simbolo(self) -> str:
        """Símbolo del estado, distinguible sin depender del color."""
        return self.value.simbolo

    @property
    def titulo(self) -> str:
        """Título corto del estado, legible sin documentación."""
        return self.value.titulo

    @property
    def ayuda(self) -> str:
        """Explicación en lenguaje llano de qué está ocurriendo."""
        return self.value.ayuda

    @property
    def color(self) -> str:
        """Color vigente del estado, resuelto contra la paleta del tema activo."""
        return estilo.token(self.value.token)

    def etiqueta(self, detalle: str = "") -> str:
        """Línea visible: símbolo + título, más el detalle concreto si lo hay."""
        base = f"{self.simbolo}  {self.titulo}"
        return f"{base} · {detalle}" if detalle else base

    def descripcion_accesible(self, detalle: str = "") -> str:
        """Texto para lectores de pantalla del estado de la enumeración."""
        return self.value.descripcion_accesible(detalle)


#: Estados en los que hay una consulta viva y Cancelar tiene sentido.
ESTADOS_ACTIVOS = frozenset({EstadoUI.PREPARANDO, EstadoUI.TRANSMITIENDO})
