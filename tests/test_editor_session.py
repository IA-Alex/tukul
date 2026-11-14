"""`EditorSession`: autosave del editor y métricas del pie.

Extracción DF-001 (ADR-0005, paso 3). El temporizador del respaldo de
recuperación, su escritura y el cálculo de estadísticas del documento dejan de
vivir en `TukulApp`. Estas pruebas fijan el contrato del objeto extraído con un
host mínimo; la integración con la ventana real se cubre en `test_app_ramas`.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tukul_core import autosave as modulo_autosave
from tukul_ui.editor_session import EditorSession


class _Sesion:
    def __init__(self):
        self.dirty = False
        self.document_path = None


class _Etiqueta:
    """Sustituto mínimo del `ttk.Label` de métricas."""

    def __init__(self):
        self.texto = ""

    def config(self, **_kw):
        self.texto = _kw["text"]


class _Editor:
    def __init__(self, host):
        self._host = host

    def get(self, inicio, fin):
        if inicio == "sel.first":
            return self._host._seleccion
        return self._host._texto

    def tag_ranges(self, nombre):
        return ("1.0", "1.5") if self._host._seleccion else ()


class _Host:
    """Host mínimo: registra los `after` sin un bucle Tk real."""

    def __init__(self, texto="", seleccion=""):
        self.session = _Sesion()
        self.closing = False
        self._texto = texto
        self._seleccion = seleccion
        self.editor_stats = _Etiqueta()
        self.programados: list[tuple[int, object, str]] = []
        self.cancelados: list[str] = []
        self._contador = 0

    @property
    def editor(self):
        return _Editor(self)

    def after(self, ms, callback):
        self._contador += 1
        ident = f"after-{self._contador}"
        self.programados.append((ms, callback, ident))
        return ident

    def after_cancel(self, ident):
        self.cancelados.append(ident)


class TestAutosave(unittest.TestCase):
    def test_schedule_programa_y_rearma(self):
        host = _Host()
        ses = EditorSession(host)
        ses.schedule_autosave()
        primero = ses.autosave_after
        self.assertIsNotNone(primero)
        ses.schedule_autosave()
        self.assertIn(primero, host.cancelados, "Reprogramar cancela el anterior")
        self.assertNotEqual(ses.autosave_after, primero)

    def test_write_escribe_respaldo_si_sucio_y_rearma(self):
        host = _Host(texto="La introducción es floja.")
        host.session.dirty = True
        with tempfile.TemporaryDirectory() as d:
            host.session.document_path = Path(d) / "articulo.md"
            with patch.object(modulo_autosave, "AUTOSAVE_DIR", Path(d) / "autosave"):
                ses = EditorSession(host)
                ses.schedule_autosave()
                ses.write_autosave()
                guardado = modulo_autosave.read_autosave(host.session.document_path)
        self.assertIn("introducción", guardado)
        self.assertIsNotNone(ses.autosave_after, "Sigue sucio: se rearma")

    def test_write_no_escribe_si_limpio(self):
        host = _Host(texto="texto")
        host.session.dirty = False
        with tempfile.TemporaryDirectory() as d:
            host.session.document_path = Path(d) / "articulo.md"
            with patch.object(modulo_autosave, "AUTOSAVE_DIR", Path(d) / "autosave"):
                ses = EditorSession(host)
                ses.write_autosave()
                self.assertIsNone(modulo_autosave.read_autosave(host.session.document_path))
        self.assertIsNone(ses.autosave_after)

    def test_write_cerrando_no_escribe_nada(self):
        host = _Host(texto="texto")
        host.session.dirty = True
        host.closing = True
        with tempfile.TemporaryDirectory() as d:
            host.session.document_path = Path(d) / "articulo.md"
            with patch.object(modulo_autosave, "AUTOSAVE_DIR", Path(d) / "autosave"):
                ses = EditorSession(host)
                ses.write_autosave()
                self.assertIsNone(modulo_autosave.read_autosave(host.session.document_path))

    def test_clear_cancela_temporizador_y_borra_respaldo(self):
        host = _Host()
        with tempfile.TemporaryDirectory() as d:
            host.session.document_path = Path(d) / "articulo.md"
            with patch("tukul_ui.editor_session.clear_autosave") as limpiar:
                ses = EditorSession(host)
                ses.schedule_autosave()
                ident = ses.autosave_after
                ses.clear_current_autosave()
        limpiar.assert_called_once_with(host.session.document_path)
        self.assertIn(ident, host.cancelados)
        self.assertIsNone(ses.autosave_after)


class TestEstadisticas(unittest.TestCase):
    def test_schedule_programa_la_actualizacion(self):
        host = _Host()
        ses = EditorSession(host)
        ses.schedule_stats()
        self.assertIsNotNone(ses.stats_after)
        ms, _cb, _id = host.programados[-1]
        self.assertEqual(ms, 300)

    def test_update_escribe_palabras_y_lectura(self):
        host = _Host(texto=" ".join(["palabra"] * 220))
        ses = EditorSession(host)
        ses.update_stats()
        self.assertEqual(host.editor_stats.texto, "220 palabras · 1 min de lectura")
        self.assertIsNone(ses.stats_after)

    def test_update_con_seleccion_incluye_el_conteo(self):
        host = _Host(texto=" ".join(["palabra"] * 400), seleccion="palabra palabra")
        ses = EditorSession(host)
        ses.update_stats()
        self.assertEqual(host.editor_stats.texto, "2 de 400 palabras · 2 min de lectura")

    def test_update_sin_texto(self):
        host = _Host(texto="")
        ses = EditorSession(host)
        ses.update_stats()
        self.assertEqual(host.editor_stats.texto, "0 palabras · 0 min de lectura")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
