"""Contrato del flujo de proyectos (`tukul_ui/proyectos.py`, hallazgo H2).

La extracción de los cuatro flujos de proyecto desde `TukulApp` mueve el punto
donde se parchean `Tk` y los diálogos. Estas pruebas fijan el contrato **desde el
módulo nuevo**, no desde `TukulApp`, para que un cambio de decoración de mocks no
pase por bueno sin ejercitar el flujo real.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from _regresion_helpers import HAS_DISPLAY

from tukul_core.models import ArticleSession, ChatMessage
from tukul_ui import proyectos
from tukul_ui.document_manager import DocumentManager
from tukul_ui.document_scope import DocumentScope


def _ventana(session: ArticleSession | None = None) -> proyectos.VentanaDeProyectos:
    """Doble mínimo de la ventana, con solo la superficie que declara el protocolo.

    No se usa `Mock(spec=...)`: convierte en mock cualquier atributo de
    INSTANCIA que no figure en el protocolo, incluida la propiedad `session`, y
    el flujo leería una copia congelada en vez de la sesión viva de
    `DocumentManager`. Un doble explícito hace visible lo que el flujo necesita:
    si se añade un método al protocolo, este doble deja de satisfacerlo.
    """

    class Doble:
        def __init__(self) -> None:
            self.docs = DocumentManager()
            self.docs.set_session(session or ArticleSession())
            self.scope = DocumentScope()
            self.status = Mock()
            self.help = None
            self.closing = False
            self._cancel_active_request = Mock()
            self._replace_editor_text = Mock()
            self._clear_history_widget = Mock()
            self._close_review_dialogs = Mock()
            self._sincronizar_estado_sync = Mock()
            self._mostrar_documento_activo = Mock()
            self.update_context = Mock()
            self.schedule_stats = Mock()
            self.append = Mock()
            self.save_document = Mock(return_value=True)

        @property
        def session(self) -> ArticleSession:
            return self.docs.session

    return Doble()

class TestGuardarProyecto(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_sin_ruta_de_artículo_avisa_y_no_pide_destino(self):
        ventana = _ventana()
        ventana.session.dirty = False

        with patch.object(proyectos.messagebox, "showinfo") as aviso, \
                patch.object(proyectos.filedialog, "asksaveasfilename") as pedir:
            proyectos.save_project(ventana)

        aviso.assert_called_once()
        pedir.assert_not_called()

    def test_cancelar_el_dialogo_no_escribe_nada(self):
        documento = self.root / "art.md"
        documento.write_text("x", encoding="utf-8")
        ventana = _ventana(ArticleSession(document_path=documento, article="x"))

        with patch.object(proyectos.filedialog, "asksaveasfilename", return_value=""):
            proyectos.save_project(ventana)

        self.assertFalse((self.root / "art.tukul.json").exists())

    def test_guarda_el_proyecto_y_lo_anuncia(self):
        documento = self.root / "art.md"
        documento.write_text("x", encoding="utf-8")
        ventana = _ventana(ArticleSession(document_path=documento, article="x"))
        destino = self.root / "art.tukul.json"

        with patch.object(proyectos.filedialog, "asksaveasfilename", return_value=str(destino)):
            proyectos.save_project(ventana)

        self.assertTrue(destino.is_file())
        ventana.status.set.assert_called_once_with("Proyecto guardado.")

    def test_error_de_escritura_se_muestra_al_usuario(self):
        documento = self.root / "art.md"
        documento.write_text("x", encoding="utf-8")
        (self.root / "sub").mkdir()
        ventana = _ventana(ArticleSession(document_path=documento, article="x"))

        # Un proyecto fuera de la carpeta del artículo: `storage` lo rechaza y el
        # flujo debe traducirlo a un modal con el motivo, no dejarlo escapar.
        with patch.object(
            proyectos.filedialog, "asksaveasfilename",
            return_value=str(self.root / "sub" / "p.tukul.json"),
        ), patch.object(proyectos.messagebox, "showerror") as error:
            proyectos.save_project(ventana)

        error.assert_called_once()
        self.assertIn("carpeta del artículo", error.call_args[0][1])


class TestAbrirProyecto(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def _proyecto(self, articulo: str, conversacion: list[ChatMessage] | None = None) -> Path:
        documento = self.root / "art.md"
        documento.write_text(articulo, encoding="utf-8")
        proyecto = self.root / "art.tukul.json"
        # El proyecto guarda rutas RELATIVAS a su carpeta (`storage.make_relative`)
        # por seguridad: una ruta absoluta se rechaza al cargar.
        proyecto.write_text(
            json.dumps({
                "version": 2,
                "document": documento.name,
                "conversation": [
                    {"role": m.role, "content": m.content} for m in (conversacion or [])
                ],
            }),
            encoding="utf-8",
        )
        return proyecto

    def test_restaura_artículo_conversación_y_ámbito(self):
        proyecto = self._proyecto(
            "TEXTO RESTAURADO",
            [ChatMessage(role="user", content="hola")],
        )
        ventana = _ventana()

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=str(proyecto)):
            proyectos.open_project(ventana)

        # El doble no se usa como `spec` de `Mock`: dentro de un `Mock(spec=...)`,
        # `_spec_class` devuelve el PROTOCOLO y `assert_called_with` formatea la
        # llamada según su firma. Se comprueba la evidencia real de la llamada.
        # `Mock` enlaza la llamada real de `__call__` a `_mock_name`: el doble
        # comprueba por `mock_calls`, que no depende de ese detalle interno.
        self.assertIn(call("TEXTO RESTAURADO"), ventana._replace_editor_text.mock_calls)
        self.assertIn(call("Tú", "hola"), ventana.append.mock_calls)
        self.assertTrue(ventana.scope.owns((self.root / "art.md").resolve()))
        ventana.status.set.assert_called_once_with("Proyecto abierto.")

    def test_restaura_el_artículo_del_proyecto_y_no_el_anterior(self):
        """Regresión de la extracción H2: el editor mostraba la sesión previa.

        Con una sesión anterior ya cargada (incluido un autosave determinista),
        abrir un proyecto debe dejar en el editor el artículo DEL PROYECTO y su
        conversación, no lo que había en pantalla.
        """
        anterior = self.root / "anterior.md"
        anterior.write_text("ARTÍCULO ANTERIOR", encoding="utf-8")
        ventana = _ventana(ArticleSession(document_path=anterior, article="ARTÍCULO ANTERIOR"))
        proyecto = self._proyecto("DEL PROYECTO", [ChatMessage(role="user", content="hola")])

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=str(proyecto)):
            proyectos.open_project(ventana)

        self.assertIn(call("DEL PROYECTO"), ventana._replace_editor_text.mock_calls)
        self.assertIn(call("Tú", "hola"), ventana.append.mock_calls)

    def test_cancelar_el_dialogo_no_cambia_la_sesión(self):
        ventana = _ventana()
        anterior = ventana.session

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=""):
            proyectos.open_project(ventana)

        self.assertIs(ventana.session, anterior)
        ventana._replace_editor_text.assert_not_called()

    def test_proyecto_inválido_muestra_el_error_y_conserva_la_sesión(self):
        proyecto = self.root / "roto.tukul.json"
        proyecto.write_text(
            json.dumps({"version": 2, "document": "no-existe.md"}), encoding="utf-8"
        )
        ventana = _ventana()
        anterior = ventana.session

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=str(proyecto)), \
                patch.object(proyectos.messagebox, "showerror") as error:
            proyectos.open_project(ventana)

        error.assert_called_once()
        self.assertIs(ventana.session, anterior)

    def test_con_solicitud_activa_pide_confirmación_y_cancela(self):
        proyecto = self._proyecto("x")
        ventana = _ventana()
        ventana.session.request_active = True

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=str(proyecto)), \
                patch.object(proyectos.messagebox, "askyesno", return_value=True), \
                patch.object(proyectos.messagebox, "showerror") as error:
            proyectos.open_project(ventana)

        ventana._cancel_active_request.assert_called_once()

    def test_rechazar_cancelar_la_solicitud_no_abre_el_proyecto(self):
        proyecto = self._proyecto("x")
        ventana = _ventana()
        ventana.session.request_active = True

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=str(proyecto)), \
                patch.object(proyectos.messagebox, "askyesno", return_value=False), \
                patch.object(proyectos.messagebox, "showerror") as error:
            proyectos.open_project(ventana)

        error.assert_not_called()
        ventana._cancel_active_request.assert_not_called()
        ventana._replace_editor_text.assert_not_called()

    def test_cambios_sin_guardar_rechazados_no_abren_el_proyecto(self):
        proyecto = self._proyecto("x")
        ventana = _ventana()
        ventana.session.dirty = True

        with patch.object(proyectos.filedialog, "askopenfilename", return_value=str(proyecto)), \
                patch.object(proyectos.messagebox, "askyesno", return_value=False):
            proyectos.open_project(ventana)

        ventana._replace_editor_text.assert_not_called()


class TestÁmbitoDeDocumento(unittest.TestCase):
    def test_reemplaza_el_objeto_en_vez_de_mutarlo(self):
        ventana = _ventana()
        original = ventana.scope

        proyectos.enter_document_scope(ventana, Path("/a.md"))

        self.assertIsNot(ventana.scope, original)
        ventana._close_review_dialogs.assert_called_once()

    def test_sin_ruta_el_ámbito_queda_limpio(self):
        ventana = _ventana()
        proyectos.enter_document_scope(ventana, Path("/a.md"))

        proyectos.enter_document_scope(ventana, None)

        self.assertIsNone(ventana.scope.document_path)


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestIntegraciónConLaVentanaReal(unittest.TestCase):
    """`TukulApp` satisface el protocolo y delega de verdad en el módulo."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        from tukul_ui.app import TukulApp

        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def test_la_ventana_real_cumple_el_protocolo(self):
        candidato: proyectos.VentanaDeProyectos = self.app  # mypy: contrato estático
        self.assertIs(candidato, self.app)

    def test_abrir_proyecto_desde_la_ventana_lo_delega_al_módulo(self):
        with patch.object(proyectos, "open_project") as delegado:
            self.app.open_project()
        delegado.assert_called_once_with(self.app)

    def test_guardar_proyecto_desde_la_ventana_lo_delega_al_módulo(self):
        with patch.object(proyectos, "save_project") as delegado:
            self.app.save_project()
        delegado.assert_called_once_with(self.app)

    def test_el_ámbito_de_la_ventana_real_se_reemplaza(self):
        self.app._enter_document_scope(Path("/otro.md"))
        self.assertEqual(self.app.scope.document_path, Path("/otro.md"))


if __name__ == "__main__":
    unittest.main()
