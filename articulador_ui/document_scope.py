"""Ámbito de interfaz asociado al documento abierto."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocumentScope:
    """Estado que solo tiene sentido mientras siga abierto un documento concreto.

    Se REEMPLAZA entero al cambiar de documento; nunca se limpia campo a campo.

    Los tres fallos críticos de la auditoría nacieron del mismo patrón: estado
    derivado del artículo anterior que sobrevivía al cambio porque alguien tenía
    que acordarse de resetear ese campo en particular.

    - La instantánea de «Deshacer último» volcaba el artículo A sobre el B.
    - El diálogo de revisión huérfano aplicaba sobre B una sugerencia de A.
    - La conversación seguía hablando de un artículo que ya no estaba en pantalla.

    Cada uno se parcheó por separado. Reunir el estado aquí convierte el parche
    en una propiedad estructural: un campo nuevo se renueva por construcción,
    sin depender de que nadie lo recuerde. El test
    `test_todo_campo_del_ambito_se_renueva_al_cambiar_de_documento` vigila
    justamente eso para los campos que se añadan en el futuro.
    """

    document_path: Path | None = None
    review_before: str = ""
    last_response: str = ""

    def owns(self, document_path: Path | None) -> bool:
        """True si este ámbito sigue correspondiendo al documento indicado."""
        return self.document_path == document_path
