"""Regresiones de la auditoría estructural — revisión y ámbito documental.

Dividido de `test_auditoria_regresion.py` (1.544 líneas, 22 clases mezclando
dominios) por dominio. Cada prueba ejecuta código de producción: si se revierte
la corrección, la prueba falla.
"""
import io
import os
import queue
import stat
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from _regresion_helpers import (
    HAS_DISPLAY,
    _display_available,
    _esperar_hilo_de_envio,
    _headless_app,
)

from tukul_core import storage
from tukul_core.llm import LLMClient, LlmError, validate_endpoint
from tukul_core.models import ArticleSession, LlmProfile
from tukul_ui.app import TukulApp
from tukul_ui.chunk_buffer import ChunkBuffer
from tukul_ui.document_scope import DocumentScope
from tukul_ui.estado import EstadoUI


@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestDeshacerRevisionEntreDocumentos(unittest.TestCase):
    """El "antes" de una sugerencia pertenece a un documento concreto."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def test_deshacer_no_vuelca_el_articulo_anterior_sobre_el_nuevo(self):
        a = self.root / "articulo_A.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        b = self.root / "articulo_B.md"
        b.write_text("TEXTO DE B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        self.app.snapshot_for_undo(self.app.editor.get("1.0", "end-1c"))

        self.app.load_document(b)
        self._settle()
        self.app.undo_review()
        self._settle()

        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO DE B")
        self.assertFalse(self.app.session.dirty, "B no debe quedar sucio con texto de A")

    def test_deshacer_sigue_funcionando_dentro_del_mismo_documento(self):
        a = self.root / "articulo_A.md"
        a.write_text("TEXTO ORIGINAL", encoding="utf-8")
        self.app.load_document(a)
        self._settle()

        self.app.snapshot_for_undo("TEXTO ORIGINAL")
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", "TEXTO REVISADO")
        self._settle()
        self.app.undo_review()
        self._settle()

        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO ORIGINAL")

@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestDialogoDeRevisionAnclado(unittest.TestCase):
    """Los hallazgos pertenecen al artículo sobre el que se calcularon."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")
        self.hallazgo = {
            "category": "gramática", "severity": "alta", "original": "floja",
            "suggestion": "POCO SÓLIDA", "reason": "registro",
        }

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _pulsar(self, dialog, etiqueta):
        from tkinter import ttk as _ttk

        botones = []
        def recorrer(widget):
            for hijo in widget.winfo_children():
                if isinstance(hijo, _ttk.Button):
                    botones.append(hijo)
                recorrer(hijo)
        recorrer(dialog)
        for boton in botones:
            if boton.cget("text") == etiqueta:
                boton.invoke()
                return True
        return False

    def test_no_aplica_hallazgos_de_otro_articulo(self):
        a = self.root / "A.md"
        a.write_text("La introducción es floja.", encoding="utf-8")
        b = self.root / "B.md"
        b.write_text("Otro artículo con redacción floja también.", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        self.app.show_findings([dict(self.hallazgo)])
        self._settle()
        dialogo = self.app.review_dialogs[0]

        self.app.load_document(b)
        self._settle()
        contenido_b = self.app.editor.get("1.0", "end-1c")

        if dialogo.winfo_exists():
            with patch("tukul_ui.dialogs.messagebox.showinfo"):
                self._pulsar(dialogo, "Aplicar")
            self._settle()

        self.assertEqual(self.app.editor.get("1.0", "end-1c"), contenido_b)
        self.assertFalse(self.app.session.dirty, "B no debe ensuciarse con una sugerencia de A")

    def test_solo_queda_un_dialogo_de_revision_abierto(self):
        a = self.root / "A.md"
        a.write_text("La introducción es floja.", encoding="utf-8")
        self.app.load_document(a)
        self._settle()

        for _ in range(4):
            self.app.show_findings([dict(self.hallazgo)])
            self._settle()

        vivos = [d for d in self.app.review_dialogs if d.winfo_exists()]
        self.assertEqual(len(vivos), 1, "Cada revisión debe reemplazar la anterior")

    def test_dentro_del_mismo_articulo_la_sugerencia_si_se_aplica(self):
        a = self.root / "A.md"
        a.write_text("La introducción es floja.", encoding="utf-8")
        self.app.load_document(a)
        self._settle()

        self.app.show_findings([dict(self.hallazgo)])
        self._settle()
        with patch("tukul_ui.dialogs.messagebox.showinfo"):
            self._pulsar(self.app.review_dialogs[0], "Aplicar")
        self._settle()

        self.assertIn("POCO SÓLIDA", self.app.editor.get("1.0", "end-1c"))
        self.assertTrue(self.app.session.dirty)

@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestAmbitoDelDocumento(unittest.TestCase):
    """Vigilancia estructural del patrón que produjo A-25, A-34 y A-35.

    Este test no comprueba un campo concreto: recorre TODOS los campos de
    DocumentScope. Si alguien añade uno nuevo y la renovación de ámbito deja de
    cubrirlo, esta prueba falla sin que nadie tenga que acordarse de ampliarla.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.app = TukulApp(self.root / "config.toml")

    def tearDown(self):
        self.app.destroy()
        self.directory.cleanup()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    @staticmethod
    def _valor_sucio(campo):
        """Un valor distinto del defecto, sea cual sea el tipo del campo."""
        if campo.name == "document_path":
            return Path("/documento/anterior.md")
        muestras = {str: "residuo del documento anterior", list: ["residuo.md"], dict: {"residuo": 1}, bool: True, int: 99}
        for tipo, valor in muestras.items():
            if campo.type in (tipo, tipo.__name__) or tipo.__name__ in str(campo.type):
                return valor
        return "residuo del documento anterior"

    def test_todo_campo_del_ambito_se_renueva_al_cambiar_de_documento(self):
        import dataclasses

        a = self.root / "a.md"
        a.write_text("TEXTO DE A", encoding="utf-8")
        b = self.root / "b.md"
        b.write_text("TEXTO DE B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()

        campos = dataclasses.fields(DocumentScope)
        self.assertGreater(len(campos), 1, "DocumentScope debe tener campos que vigilar")
        for campo in campos:
            setattr(self.app.scope, campo.name, self._valor_sucio(campo))

        self.app.load_document(b)
        self._settle()

        limpio = DocumentScope(document_path=b.resolve())
        for campo in campos:
            self.assertEqual(
                getattr(self.app.scope, campo.name),
                getattr(limpio, campo.name),
                f"El campo '{campo.name}' sobrevivió al cambio de documento. "
                f"El ámbito debe reemplazarse entero en _enter_document_scope.",
            )

    def test_el_ambito_es_un_objeto_nuevo_no_el_mismo_mutado(self):
        a = self.root / "a.md"
        a.write_text("A", encoding="utf-8")
        b = self.root / "b.md"
        b.write_text("B", encoding="utf-8")

        self.app.load_document(a)
        self._settle()
        ambito_a = self.app.scope

        self.app.load_document(b)
        self._settle()

        self.assertIsNot(self.app.scope, ambito_a, "Reemplazar, no limpiar campo a campo")
        self.assertTrue(self.app.scope.owns(b.resolve()))
        self.assertFalse(self.app.scope.owns(a.resolve()))

    def test_guardar_como_conserva_el_ambito_y_sigue_a_la_ruta_nueva(self):
        a = self.root / "a.md"
        a.write_text("TEXTO ORIGINAL", encoding="utf-8")
        self.app.load_document(a)
        self._settle()
        self.app.snapshot_for_undo("TEXTO ORIGINAL")
        destino = self.root / "renombrado.md"

        with patch("tukul_ui.app.filedialog.asksaveasfilename", return_value=str(destino)):
            self.assertTrue(self.app.save_document(save_as=True))
        self._settle()

        # Renombrar no es cambiar de artículo: el deshacer debe seguir vivo.
        self.assertTrue(self.app.scope.owns(destino.resolve()))
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", "TEXTO MODIFICADO")
        self.app.undo_review()
        self._settle()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "TEXTO ORIGINAL")
