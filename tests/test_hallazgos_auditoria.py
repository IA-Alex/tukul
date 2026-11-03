"""Regresiones de los hallazgos de `docs/audit/audit-report-2026-11-02-produce.md`.

Cada prueba fija el síntoma concreto del informe, no la implementación: si el
comportamiento vuelve, el test falla con el nombre del hallazgo.
"""
import logging
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tukul_core.storage as storage
from tukul_core import autosave
from tukul_core.review import MAX_RESULT_CHARS, parse_findings
from tukul_ui import estilo as es
from tukul_ui.app import TukulApp


class _BackendFalso:
    """Doble de `keyring` con un guion de errores controlado."""

    def __init__(self, error: BaseException | str) -> None:
        self.error = error

    def get_password(self, _servicio: str, _perfil: str) -> str:
        if isinstance(self.error, BaseException):
            raise self.error
        return self.error


class TestPrivacidadDeEstado(unittest.TestCase):
    """M-4: estado, config y autosave contienen datos privados del autor."""

    def test_estado_json_se_crea_solo_legible_por_el_dueno(self):
        with tempfile.TemporaryDirectory() as directorio:
            config = Path(directorio) / "config.toml"
            storage.save_ui_state({"conversations": {"a.md": ["texto privado"]}}, config)
            modo = stat.S_IMODE(storage.estado_ui_path(config).stat().st_mode)
            self.assertEqual(modo, 0o600, "estado.json no debe ser legible por otros usuarios")

    def test_config_toml_no_se_crea_mundo_legible(self):
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "config.toml"
            storage.atomic_write(destino, "[llm]\n", mode=0o600)
            self.assertEqual(stat.S_IMODE(destino.stat().st_mode), 0o600)


class TestLlaveroRoto(unittest.TestCase):
    """M-5: un backend caído no puede reportarse como «no hay key»."""

    def test_entrada_inexistente_sigue_siendo_cadena_vacia(self):
        original = storage.keyring
        storage.keyring = _BackendFalso(_SinEntradaError())
        try:
            self.assertEqual(storage.load_key("perfil"), "")
        finally:
            storage.keyring = original

    def test_backend_caido_lanza_un_error_distinguible(self):
        original = storage.keyring
        storage.keyring = _BackendFalso(RuntimeError("Secret Service no responde"))
        try:
            with self.assertRaises(storage.KeyringUnavailableError):
                storage.load_key("perfil")
        finally:
            storage.keyring = original


class _SinEntradaError(Exception):
    def __str__(self) -> str:
        return "No password is set"


class TestTopeDelAutosave(unittest.TestCase):
    """M-6: un respaldo sustituido desde fuera no debe cargarse entero."""

    def test_autosave_por_encima_del_tope_se_ignora(self):
        with tempfile.TemporaryDirectory() as directorio:
            documento = Path(directorio) / "articulo.md"
            documento.write_text("# Artículo", encoding="utf-8")
            respaldo = autosave._autosave_path(documento)
            respaldo.parent.mkdir(parents=True, exist_ok=True)
            respaldo.write_text("x" * (autosave.MAX_AUTOSAVE_BYTES + 1), encoding="utf-8")
            try:
                self.assertIsNone(autosave.read_autosave(documento))
            finally:
                respaldo.unlink(missing_ok=True)


class TestTopeDeRevision(unittest.TestCase):
    """M-6: `raw_decode` no debe materializar un JSON arbitrariamente grande."""

    def test_resultado_desmesurado_no_se_parsea(self):
        enorme = "{" + "a" * (MAX_RESULT_CHARS + 10)
        self.assertEqual(parse_findings(enorme), [])

    def test_hallazgos_normales_siguen_parseandose(self):
        valido = ('{"findings": [{"category": "ortografía", "severity": "alta", '
                  '"original": "casa", "suggestion": "caza", "reason": "h"}]}')
        self.assertEqual(len(parse_findings(valido)), 1)


class TestFuenteConReserva(unittest.TestCase):
    """M-7: sin «Inter» instalada la interfaz no debe caer en una fuente ajena."""

    def tearDown(self) -> None:
        es._familia_activa = None

    def test_usa_inter_cuando_existe(self):
        self.assertEqual(es.resolver_familia(["Inter", "DejaVu Sans"]), "Inter")

    def test_cae_a_una_sans_del_sistema_si_inter_falta(self):
        self.assertEqual(es.resolver_familia(["DejaVu Sans", "Liberation Sans"]), "DejaVu Sans")

    def test_sin_candidatas_conserva_la_familia_declarada(self):
        self.assertEqual(es.resolver_familia(["Comic Sans MS"]), es.FAMILIA)


class TestTamanoDeDialogo(unittest.TestCase):
    """M-8: los diálogos no pueden superar la pantalla del usuario."""

    def test_cabe_en_un_portatil_pequeno(self):
        self.assertEqual(es.tamano_ventana(700, 620, 1366, 768, minimo=(560, 400)),
                         "700x620")

    def test_pantalla_baja_reduce_la_altura(self):
        self.assertEqual(es.tamano_ventana(700, 620, 1366, 600, minimo=(560, 400)),
                         "700x536")

    def test_pantalla_minuscula_respeta_minimo_solo_si_cabe(self):
        self.assertEqual(es.tamano_ventana(760, 520, 640, 480, minimo=(620, 380)),
                         "608x416")


class TestErrorVisibleConRuta(unittest.TestCase):
    """M-10: el aviso de error debe decir dónde está el registro."""

    def test_show_error_incluye_la_ruta_del_log(self):
        app = MagicMock()
        con_archivo = logging.FileHandler(Path(tempfile.gettempdir()) / "tukul.log", delay=True)
        try:
            with patch("tukul_ui.app.logger.handlers", [con_archivo]), \
                    patch("tukul_ui.app.messagebox.showerror") as dialogo:
                TukulApp.show_error(app, "No se pudo abrir", "detalle técnico")
            texto = dialogo.call_args[0][1]
            self.assertIn("tukul.log", texto)
        finally:
            con_archivo.close()


class TestAvisoDeLlaveroCaido(unittest.TestCase):
    """M-5 (UI): el evento llega al pie con una instrucción accionable."""

    def test_el_evento_actualiza_la_barra_de_estado(self):
        app = MagicMock()
        TukulApp._dispatch_ui_event(app, ("keyring_unavailable", "trabajo"))
        mensaje = app.status.set.call_args[0][0]
        self.assertIn("llavero", mensaje.lower())
        self.assertIn("trabajo", mensaje)
        self.assertIn("variable de entorno", mensaje)


class TestSinShimDeColor(unittest.TestCase):
    """M-1 / B-6: no queda la vista de compatibilidad `colores()`."""

    def test_el_shim_esta_retirado(self):
        self.assertFalse(hasattr(es, "colores"))
        self.assertFalse(hasattr(es, "COLORS"))
