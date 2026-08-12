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
    """Presentación de un estado de la conversación."""

    clave: str
    simbolo: str
    titulo: str
    ayuda: str
    color: str

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
        estilo.ESTADO_NEUTRO,
    )
    PREPARANDO = Estado(
        "preparando", "◐", "Preparando contexto",
        "Buscando en tus artículos locales lo relevante para la consulta",
        estilo.ESTADO_PROCESO,
    )
    TRANSMITIENDO = Estado(
        "transmitiendo", "◉", "Recibiendo respuesta",
        "El modelo está escribiendo; puedes cancelar en cualquier momento",
        estilo.ACENTO,
    )
    EXITO = Estado(
        "exito", "✓", "Respuesta completa",
        "La respuesta llegó entera",
        estilo.ESTADO_EXITO,
    )
    ERROR = Estado(
        "error", "✕", "No se pudo completar",
        "Revisa la conexión, el modelo o los límites del perfil",
        estilo.ESTADO_ERROR,
    )
    CANCELADO = Estado(
        "cancelado", "⊘", "Cancelado",
        "Se descartará la respuesta que llegue tarde",
        estilo.ESTADO_AVISO,
    )

    @property
    def simbolo(self) -> str:
        return self.value.simbolo

    @property
    def titulo(self) -> str:
        return self.value.titulo

    @property
    def ayuda(self) -> str:
        return self.value.ayuda

    @property
    def color(self) -> str:
        return self.value.color

    def etiqueta(self, detalle: str = "") -> str:
        """Línea visible: símbolo + título, más el detalle concreto si lo hay."""
        base = f"{self.simbolo}  {self.titulo}"
        return f"{base} · {detalle}" if detalle else base

    def descripcion_accesible(self, detalle: str = "") -> str:
        return self.value.descripcion_accesible(detalle)


#: Estados en los que hay una consulta viva y Cancelar tiene sentido.
ESTADOS_ACTIVOS = frozenset({EstadoUI.PREPARANDO, EstadoUI.TRANSMITIENDO})
