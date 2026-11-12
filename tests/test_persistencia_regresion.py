"""Regresiones de la auditoría estructural — persistencia y perfiles.

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


class TestEscrituraAtomica(unittest.TestCase):
    def test_preserva_los_permisos_del_destino(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "articulo.md"
            target.write_text("original", encoding="utf-8")
            os.chmod(target, 0o644)

            storage.atomic_write(target, "nuevo contenido")

            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            self.assertEqual(target.read_text(encoding="utf-8"), "nuevo contenido")

    def test_archivo_nuevo_no_hereda_permisos_laxos(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nuevo.md"
            storage.atomic_write(target, "x")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

class TestRutasDeProyecto(unittest.TestCase):
    def test_proyecto_fuera_del_arbol_del_articulo_explica_la_restriccion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "art.md"
            document.write_text("x", encoding="utf-8")
            (root / "proyectos").mkdir()
            session = ArticleSession(document_path=document, article="x")

            with self.assertRaises(ValueError) as ctx:
                storage.save_project(session, root / "proyectos" / "p.tukul.json")

            self.assertIn("carpeta del artículo", str(ctx.exception))
            self.assertNotIn("subpath", str(ctx.exception))

class TestPerfilesInvalidos(unittest.TestCase):
    def test_perfil_corrupto_se_ignora_dejando_rastro(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                '[llm]\nactive_profile = "malo"\n\n'
                '[profiles.malo]\nprovider = "openai_compatible"\n'
                'endpoint = "https://x/y"\nmodel = "m"\ntemperature = 9.0\n',
                encoding="utf-8",
            )

            with patch.object(storage.logger, "warning") as warn:
                profiles, active = storage.load_profiles(config)

            self.assertNotIn("malo", profiles)
            self.assertEqual(active, "default")
            self.assertTrue(
                any("malo" in str(call) for call in warn.call_args_list),
                "El perfil descartado debe aparecer en el log",
            )

class TestKeysDeSesion(unittest.TestCase):
    """Actualizar una key no debe desalojar la de otro perfil."""

    def _holder(self, maximo: int):
        holder = TukulApp.__new__(TukulApp)
        holder.session_keys = {}
        holder._session_keys_max = maximo
        return holder

    def test_actualizar_una_key_existente_no_desaloja_a_nadie(self):
        holder = self._holder(3)
        for name in ("p1", "p2", "p3"):
            holder._add_session_key(name, f"k-{name}")

        holder._add_session_key("p2", "k-p2-nueva")

        self.assertEqual(len(holder.session_keys), 3)
        self.assertEqual(holder.session_keys["p1"], "k-p1")
        self.assertEqual(holder.session_keys["p2"], "k-p2-nueva")

    def test_insertar_una_key_nueva_desaloja_la_menos_reciente(self):
        holder = self._holder(3)
        for name in ("p1", "p2", "p3"):
            holder._add_session_key(name, f"k-{name}")
        holder._add_session_key("p2", "k-p2-nueva")  # p2 pasa a ser la más reciente

        holder._add_session_key("p4", "k-p4")

        self.assertNotIn("p1", holder.session_keys)
        self.assertEqual(set(holder.session_keys), {"p2", "p3", "p4"})

class TestDocumentManagerEsElDuenoDeLaPersistencia(unittest.TestCase):
    """Los métodos que la app duplicaba deben existir y comportarse."""

    def test_save_project_traduce_el_error_de_ruta(self):
        from tukul_ui.document_manager import DocumentManager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "art.md"
            document.write_text("x", encoding="utf-8")
            (root / "sub").mkdir()

            ok, error = DocumentManager().save_project(
                ArticleSession(document_path=document, article="x"),
                root / "sub" / "p.tukul.json",
            )

            self.assertFalse(ok)
            self.assertIn("carpeta del artículo", error)

    def test_open_project_devuelve_error_si_falta_el_articulo(self):
        import json

        from tukul_ui.document_manager import DocumentManager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "p.tukul.json"
            project.write_text(
                json.dumps({"version": 2, "document": "no-existe.md"}), encoding="utf-8"
            )

            ok, error, _session = DocumentManager().open_project(project)

            self.assertFalse(ok)
            self.assertIn("No existe el artículo", error)

@unittest.skipUnless(HAS_DISPLAY, "requiere un servidor X")
class TestGestionDePerfiles(unittest.TestCase):
    """El diálogo de configuración permite crear y borrar perfiles."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        config = self.root / "config.toml"
        config.write_text(
            '[llm]\nactive_profile = "p1"\n\n'
            '[profiles.p1]\nprovider = "openai_compatible"\n'
            'endpoint = "https://x.example/v1/chat/completions"\n'
            'model = "m1"\napi_key_env = "CLAVE_PERFILES"\n\n'
            '[profiles.p2]\nprovider = "openai_compatible"\n'
            'endpoint = "https://x.example/v1/chat/completions"\n'
            'model = "m2"\napi_key_env = "CLAVE_PERFILES"\n',
            encoding="utf-8",
        )
        os.environ["CLAVE_PERFILES"] = "clave"
        self.addCleanup(lambda: os.environ.pop("CLAVE_PERFILES", None))
        self.app = TukulApp(config)
        self.addCleanup(self.app.destroy)
        self._settle()

    def _settle(self):
        for _ in range(5):
            self.app.update()
            self.app.update_idletasks()

    def _widgets(self):
        from tkinter import ttk

        dialogo = next(w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel")

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        widgets = list(walk(dialogo))
        return dialogo, widgets

    def test_el_dialogo_lista_todos_los_perfiles(self):
        from tkinter import ttk

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        combo = next(
            w for w in widgets
            if isinstance(w, ttk.Combobox) and w.cget("values") == ("default", "p1", "p2")
        )
        self.assertEqual(list(combo.cget("values")), ["default", "p1", "p2"])

    def test_borrar_un_perfil_lo_quita_y_guardar_actualiza_la_app(self):
        from tkinter import ttk

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}

        with patch("tukul_ui.dialogs.messagebox.askyesno", return_value=True):
            buttons["Borrar"].invoke()  # borra el activo «p1»
        self._settle()

        with patch("tukul_ui.dialogs.messagebox.showinfo") as info, \
                patch("tukul_ui.dialogs.messagebox.showerror") as error:
            buttons["Guardar"].invoke()
        self._settle()

        self.assertNotIn("p1", self.app.profiles, "El perfil borrado ya no debe existir")
        self.assertIn("p2", self.app.profiles)
        error.assert_not_called()
        info.assert_called_once()

    def test_guardar_sin_llavero_no_deja_el_dialogo_colgado(self):
        """Sin llavero de sistema (CI) el guardado no abre un error modal.

        `save()` persiste primero y luego la credencial; si el backend falla,
        mostraba `showerror`, que en una sesión sin interacción espera un clic
        para siempre. El perfil sí se guarda: la key queda solo en sesión, que
        es el comportamiento documentado sin llavero.
        """
        from tkinter import ttk

        from tukul_core import storage

        original = storage.keyring
        storage.keyring = None
        self.addCleanup(lambda: setattr(storage, "keyring", original))

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}

        with patch("tukul_ui.dialogs.messagebox.showinfo"), \
                patch("tukul_ui.dialogs.messagebox.showerror") as error:
            buttons["Guardar"].invoke()
        self._settle()

        error.assert_not_called()
        self.assertIn("p1", self.app.profiles, "Sin llavero el perfil se guarda igual")

    def test_nuevo_perfil_se_crea_y_pasa_a_ser_activo(self):
        from tkinter import ttk

        from tukul_ui.dialogs import show_settings_dialog

        show_settings_dialog(self.app)
        self._settle()
        _dialogo, widgets = self._widgets()
        buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}

        with patch("tukul_ui.dialogs.simpledialog.askstring", return_value="p3"):
            buttons["Nuevo"].invoke()
        self._settle()

        with patch("tukul_ui.dialogs.messagebox.showinfo"):
            buttons["Guardar"].invoke()
        self._settle()

        self.assertIn("p3", self.app.profiles, "El perfil nuevo debe guardarse")
        self.assertEqual(self.app.active_profile, "p3", "El perfil nuevo pasa a ser el activo")
