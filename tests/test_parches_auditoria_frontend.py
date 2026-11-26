"""Regresión de los parches de la auditoría de frontend (2026-11-25).

Cubre los tres hallazgos CONFIRMED del informe `frontend-audit`:

- **FA-002** doble envío del placeholder: un segundo Enter inmediato (sin
  `FocusIn` intermedio) podía enviar el texto del placeholder como mensaje real.
- **FA-003** coste del recorte del historial: se recontaba
  `tag_ranges("separacion")` —O(total de turnos)— en cada `append`.
- **FA-001** reparto del tiempo de espera al cerrar: el primer worker podía
  consumir todo el plazo y los siguientes recibían `join(timeout=0)`.

Cada prueba ejecuta el código de producción; ninguna reimplementa la lógica.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tukul_ui import app as modulo_app
from tukul_ui.app import MAX_HISTORIAL_TURNOS, TukulApp
from tukul_ui.worker_threads import WorkerThreads

CLAVE = "CLAVE_PRUEBA_PARCHES_AUDITORIA"
CONFIG = (
    '[llm]\nactive_profile = "p"\n\n[profiles.p]\n'
    'provider = "openai_compatible"\n'
    'endpoint = "https://api.example.com/v1/chat/completions"\n'
    'model = "m"\napi_key_env = "' + CLAVE + '"\n'
)


def _hay_display() -> bool:
    try:
        raiz = tk.Tk()
    except tk.TclError:
        return False
    raiz.destroy()
    return True


HAY_DISPLAY = _hay_display()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class _BaseApp(unittest.TestCase):
    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.config = self.raiz / "config.toml"
        self.config.write_text(CONFIG, encoding="utf-8")
        os.environ[CLAVE] = "clave"
        self.app = TukulApp(self.config)
        self._asentar()

    def tearDown(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass
        WorkerThreads.esperar(1.0)
        os.environ.pop(CLAVE, None)
        self.directorio.cleanup()

    def _asentar(self, veces: int = 5):
        for _ in range(veces):
            self.app.update()
            self.app.update_idletasks()
        WorkerThreads.esperar(1.0)


class TestDobleEnvioDePlaceholder(_BaseApp):
    """FA-002: el placeholder nunca se envía como mensaje del usuario."""

    def _input_vacio_con_placeholder(self):
        """Deja el campo en el estado «vacío, con placeholder visible»."""
        self.app.input.delete("1.0", "end")
        self.app.input.insert("1.0", self.app._placeholder_texto)
        self.app._placeholder_activo = True

    def test_enter_sobre_placeholder_no_envia_nada(self):
        self._input_vacio_con_placeholder()
        with patch.object(self.app, "request") as pedir:
            self.app._enviar_desde_input()
        pedir.assert_not_called()
        self.assertEqual(self.app.session.conversation, [])

    def test_enter_sobre_placeholder_con_bandera_desincronizada_no_envia(self):
        """El caso del orden de eventos: la bandera dice «no activo» pero el
        contenido visible es exactamente el placeholder. Antes se enviaba."""
        self.app.input.delete("1.0", "end")
        self.app.input.insert("1.0", self.app._placeholder_texto)
        self.app._placeholder_activo = False  # bandera desincronizada a propósito
        with patch.object(self.app, "request") as pedir:
            self.app._enviar_desde_input()
        pedir.assert_not_called()

    def test_texto_real_con_prefijo_del_placeholder_si_se_envia(self):
        """El guardia es por CONTENIDO exacto: si el usuario escribió algo más
        (aunque empiece como el placeholder), su mensaje se envía."""
        self.app.input.delete("1.0", "end")
        self.app.input.insert("1.0", self.app._placeholder_texto + " y algo más")
        self.app._placeholder_activo = True
        with patch.object(self.app, "_resolver_credenciales", return_value="k"), \
                patch.object(self.app, "request") as pedir:
            self.app._enviar_desde_input()
        pedir.assert_called_once()
        self.assertIn("algo más", pedir.call_args[0][0])


class TestRecorteDelHistorial(_BaseApp):
    """FA-003: el tope del historial no reescanea el widget en cada turno."""

    def test_el_contador_sigue_a_los_turnos_insertados(self):
        # El arranque ya deja un turno de bienvenida; se parte de ahí.
        base = self.app._historial_turnos
        for i in range(5):
            self.app.append("Tú", f"mensaje {i}")
        self.assertEqual(self.app._historial_turnos, base + 5)

    def test_el_recorte_rebaja_el_contador_al_tope(self):
        limite = MAX_HISTORIAL_TURNOS
        # Insertar el tope + unos pocos y comprobar que el contador no lo supera.
        for i in range(limite + 3):
            self.app.append("Tú", f"mensaje {i}")
        self.assertLessEqual(self.app._historial_turnos, limite + 1)
        # El recorte real ocurre: no se conserva todo lo insertado.
        separadores = self.app.history.tag_ranges("separacion")
        self.assertLessEqual(len(separadores) // 2, limite + 1)

    def test_limpiar_el_historial_resetea_el_contador(self):
        self.app.append("Tú", "hola")
        self.app._clear_history_widget()
        self.assertEqual(self.app._historial_turnos, 0)

    def test_no_reescanea_tag_ranges_en_cada_append_por_debajo_del_tope(self):
        """Con el historial por debajo del tope, ningún `append` recorre el
        widget: el contador evita el `tag_ranges` que antes era O(total)."""
        llamadas = {"n": 0}
        original = self.app.history.tag_ranges

        def _contar(*args, **kwargs):
            if args and args[0] == "separacion":
                llamadas["n"] += 1
            return original(*args, **kwargs)

        with patch.object(self.app.history, "tag_ranges", side_effect=_contar):
            for i in range(10):
                self.app.append("Tú", f"mensaje {i}")
        self.assertEqual(llamadas["n"], 0,
                         "append no debe recontar los separadores por debajo del tope")


class TestRepartoDeEsperaAlCerrar(unittest.TestCase):
    """FA-001: `WorkerThreads.esperar` da a cada hilo su ventana de gracia."""

    def setUp(self):
        WorkerThreads.reset()

    def tearDown(self):
        WorkerThreads.esperar(1.0)
        WorkerThreads.reset()

    def test_ningun_hilo_recibe_cero_tiempo_por_culpa_de_otro(self):
        """Todos los hilos terminan dentro del plazo aunque el primero sea lento.

        Con el reparto secuencial, el primer hilo consumía el plazo entero y el
        segundo recibía `join(timeout≈0)`: quedaba vivo al devolver `esperar`.
        """

        def lento():
            time.sleep(0.15)

        def rapido():
            time.sleep(0.01)

        t_lento = WorkerThreads.start(lento)
        t_rapido = WorkerThreads.start(rapido)
        vivos = WorkerThreads.esperar(1.0)
        self.assertNotIn(t_rapido, vivos,
                         "el hilo rápido quedó vivo: no recibió su ventana de gracia")
        self.assertNotIn(t_lento, vivos)

    def test_el_tope_total_no_se_supera(self):
        """El reparto reparte el MISMO presupuesto; no lo multiplica por hilo."""
        stop = threading.Event()

        def eterno():
            stop.wait(5.0)

        for _ in range(3):
            WorkerThreads.start(eterno)
        inicio = time.monotonic()
        vivos = WorkerThreads.esperar(0.3)
        transcurrido = time.monotonic() - inicio
        stop.set()
        self.assertLess(transcurrido, 1.5, "esperar excedió con creces el tope total")
        self.assertEqual(len(vivos), 3, "los hilos eternos deben devolverse como vivos")


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestFocoInicialDeDialogos(_BaseApp):
    """FA-004: `abrir_dialogo` deja el foco en un control del diálogo.

    Bajo un `Xvfb` sin gestor de ventanas, `focus_get()` puede devolver `None`
    aunque `focus_set()` se haya llamado (el toplevel nunca recibe el foco de
    X). Por eso la prueba determinista comprueba la SELECCIÓN del primer
    control enfocable, que es la lógica propia del ayudante, y no el foco de X.
    """

    def test_elige_el_primer_control_enfocable_en_orden_de_creacion(self):
        from tukul_ui import dialogs_base as db

        dialogo, cuerpo = db.abrir_dialogo(self.app, "Prueba", modal=True)
        primero = ttk.Entry(cuerpo)
        primero.pack()
        ttk.Entry(cuerpo).pack()
        dialogo.update_idletasks()
        self.assertIs(db._primer_enfocable(dialogo), primero,
                      "no se eligió el primer control enfocable del diálogo")
        dialogo.destroy()

    def test_no_cambia_el_foco_si_ya_esta_dentro(self):
        from tukul_ui import dialogs_base as db

        dialogo, cuerpo = db.abrir_dialogo(self.app, "Prueba", modal=True)
        ttk.Entry(cuerpo).pack()
        segundo = ttk.Entry(cuerpo)
        segundo.pack()
        dialogo.update_idletasks()
        tocados: list[str] = []

        # Doble que, si se llegara a consultar, registraría el intento de foco.
        def _no_debe_usarse(_d):
            class _Doble:
                def focus_set(self):
                    tocados.append("pisado")

            return _Doble()

        original = db._primer_enfocable
        db._primer_enfocable = _no_debe_usarse
        try:
            # `segundo` está DENTRO del diálogo: el ayudante debe salir sin tocar.
            with patch.object(dialogo, "focus_get", return_value=segundo):
                db.enfocar_primer_control(dialogo)
        finally:
            db._primer_enfocable = original
        self.assertEqual(tocados, [],
                         "pisó un foco ya establecido dentro del diálogo")
        dialogo.destroy()

    def test_devuelve_foco_al_primer_control_cuando_no_hay_ninguno(self):
        from tukul_ui import dialogs_base as db

        dialogo, cuerpo = db.abrir_dialogo(self.app, "Prueba", modal=True)
        ttk.Entry(cuerpo).pack()
        dialogo.update_idletasks()
        tocados: list[str] = []
        original = db._primer_enfocable

        def _registrar(_d):
            class _Doble:
                def focus_set(self):
                    tocados.append("foco")

            return _Doble()

        db._primer_enfocable = _registrar
        try:
            with patch.object(dialogo, "focus_get", return_value=None):
                db.enfocar_primer_control(dialogo)
        finally:
            db._primer_enfocable = original
        self.assertEqual(tocados, ["foco"],
                         "sin foco dentro, debía enfocar el primer control")
        dialogo.destroy()


@unittest.skipUnless(HAY_DISPLAY, "requiere un servidor X")
class TestSaneoMcpPersistido(_BaseApp):
    """FA-006: un `estado.json` manipulado no puebla el formulario MCP."""

    def _abrir(self) -> tk.Toplevel | None:
        from tukul_ui.mcp_dialog import show_mcp_dialog

        # `show_mcp_dialog(parent=…)` crea su Toplevel como hijo de `parent`.
        padre = tk.Toplevel(self.app)
        show_mcp_dialog(self.app, padre, lambda: None)
        self.app.update()
        self.app.update_idletasks()
        for w in padre.winfo_children():
            if isinstance(w, tk.Toplevel) and w.winfo_children():
                return w
        return None

    @staticmethod
    def _valores_de_entradas(widget) -> list[str]:
        encontrados: list[str] = []
        for hijo in widget.winfo_children():
            if isinstance(hijo, ttk.Entry):
                encontrados.append(hijo.get())
            encontrados.extend(TestSaneoMcpPersistido._valores_de_entradas(hijo))
        return encontrados

    def test_comando_con_nul_no_se_inyecta(self):
        self.app.ui_state["mcp_server"] = {"command": "malo\x00bin", "args": []}
        dialogo = self._abrir()
        self.assertIsNotNone(dialogo)
        valores = self._valores_de_entradas(dialogo)
        self.assertNotIn("malo\x00bin", valores,
                         "el carácter nulo persistido llegó al formulario")
        dialogo.destroy()

    def test_args_no_textuales_se_descartan(self):
        self.app.ui_state["mcp_server"] = {"command": "ok", "args": [123, {"x": 1}]}
        dialogo = self._abrir()
        self.assertIsNotNone(dialogo)
        valores = self._valores_de_entradas(dialogo)
        self.assertIn("[]", valores,
                      "los argumentos no textuales debían restaurarse a lista vacía")
        dialogo.destroy()


if __name__ == "__main__":
    unittest.main()
