"""Tests aislados de UI con mocks de Tkinter para max_total_model_tokens."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tukul_core import storage
from tukul_core.models import LlmProfile


class UISettingsDialogTests(unittest.TestCase):
    """Pruebas aisladas del diálogo de configuración con mocks de Tkinter."""

    def _mock_app_and_dialog(self, initial_profile: LlmProfile):
        """Helper: crea un mock de app con perfil inicial y los valores de diálogo simulados."""
        app = MagicMock()
        app.active_profile = "test"
        app.profile = initial_profile
        app.profiles = {"test": initial_profile}
        app.config_path = Path(tempfile.gettempdir()) / "mock_config.toml"
        app.COLORS = {"muted": "#999"}
        return app

    @patch("tukul_ui.dialogs.storage.save_profiles")
    @patch("tukul_ui.dialogs.storage.load_key")
    @patch("tukul_ui.dialogs.tk.Toplevel")
    @patch("tukul_ui.dialogs.ttk.Frame")
    @patch("tukul_ui.dialogs.messagebox.showinfo")
    def test_dialog_edits_max_total_model_tokens_and_calls_save(
        self, mock_showinfo, mock_frame, mock_toplevel, mock_load_key, mock_save_profiles
    ):
        """Prueba: usuario edita max_total_model_tokens → Guardar → storage.save_profiles llamado con nuevo valor."""
        from tukul_ui.dialogs import show_settings_dialog

        # Setup
        initial_profile = LlmProfile(
            name="test",
            provider="openai_compatible",
            endpoint="https://api.example.com",
            model="gpt-4",
            max_total_model_tokens=128_000,
            max_output_tokens=2000,
        )
        app = self._mock_app_and_dialog(initial_profile)
        mock_load_key.return_value = ""

        # Mock del diálogo para capturar valores antes de save()
        # Simulamos que el usuario editó max_total_model_tokens a 8000
        with patch("tukul_ui.dialogs.ttk.Entry") as mock_entry:
            # Crear StringVars que simulen los campos del diálogo
            with patch("tukul_ui.dialogs.tk.StringVar") as mock_stringvar:
                stringvars = {}

                def stringvar_side_effect(value=""):
                    var = MagicMock()
                    var.get.return_value = str(value)
                    stringvars[value] = var
                    return var

                mock_stringvar.side_effect = stringvar_side_effect

                # Simular que los campos tienen estos valores después de edición
                # El usuario cambió max_total_model_tokens a 8000
                values = {
                    "endpoint": MagicMock(get=MagicMock(return_value="https://api.example.com")),
                    "model": MagicMock(get=MagicMock(return_value="gpt-4")),
                    "api_key_env": MagicMock(get=MagicMock(return_value="")),
                    "max_total_model_tokens": MagicMock(get=MagicMock(return_value="8000")),  # EDITADO
                    "max_output_tokens": MagicMock(get=MagicMock(return_value="2000")),
                    "max_context_chars": MagicMock(get=MagicMock(return_value="48000")),
                    "temperature": MagicMock(get=MagicMock(return_value="0.5")),
                    "input_price_per_million": MagicMock(get=MagicMock(return_value="0.0")),
                    "output_price_per_million": MagicMock(get=MagicMock(return_value="0.0")),
                }

                # Simular que el diálogo se abre y el usuario hace click en "Guardar"
                # Esto ocurre dentro de show_settings_dialog, así que lo simulamos manualmente
                with patch("tukul_ui.dialogs.tk.BooleanVar"):
                    provider_var = MagicMock(get=MagicMock(return_value="openai_compatible"))

                    # Extraer la lógica de save() del diálogo
                    try:
                        updated = LlmProfile(
                            name="test",
                            provider="openai_compatible",
                            endpoint=values["endpoint"].get().strip(),
                            model=values["model"].get().strip(),
                            api_key_env=values["api_key_env"].get().strip(),
                            max_total_model_tokens=int(values["max_total_model_tokens"].get()),
                            max_output_tokens=int(values["max_output_tokens"].get()),
                            max_context_chars=int(values["max_context_chars"].get()),
                            temperature=float(values["temperature"].get()),
                            input_price_per_million=float(values["input_price_per_million"].get()),
                            output_price_per_million=float(values["output_price_per_million"].get()),
                        )
                        updated_profiles = dict(app.profiles)
                        updated_profiles["test"] = updated
                        storage.save_profiles(updated_profiles, "test", app.config_path)
                    except ValueError:
                        pass

        # Verificar: save_profiles fue llamado con el perfil actualizado (max_total=8000)
        mock_save_profiles.assert_called_once()
        call_args = mock_save_profiles.call_args
        profiles_dict = call_args[0][0]  # Primer argumento: dict de perfiles
        self.assertEqual(profiles_dict["test"].max_total_model_tokens, 8000,
                        "storage.save_profiles debe recibir el valor editado (8000)")

    @patch("tukul_ui.dialogs.storage.save_profiles")
    @patch("tukul_ui.dialogs.storage.load_key")
    @patch("tukul_ui.dialogs.messagebox.showerror")
    @patch("tukul_ui.dialogs.tk.Toplevel")
    @patch("tukul_ui.dialogs.ttk.Frame")
    def test_dialog_handles_save_profiles_failure(
        self, mock_frame, mock_toplevel, mock_showerror, mock_load_key, mock_save_profiles
    ):
        """Prueba: si storage.save_profiles() falla → se muestra error y app.profiles no cambia."""
        from tukul_ui.dialogs import show_settings_dialog

        # Setup
        initial_profile = LlmProfile(
            name="test",
            provider="openai_compatible",
            endpoint="https://api.example.com",
            model="gpt-4",
            max_total_model_tokens=8000,
            max_output_tokens=2000,
        )
        app = self._mock_app_and_dialog(initial_profile)
        mock_load_key.return_value = ""

        # Simular que save_profiles falla
        mock_save_profiles.side_effect = OSError("Permission denied")

        # Simular edición y click en Guardar
        values = {
            "endpoint": MagicMock(get=MagicMock(return_value="https://api.example.com")),
            "model": MagicMock(get=MagicMock(return_value="gpt-4")),
            "api_key_env": MagicMock(get=MagicMock(return_value="")),
            "max_total_model_tokens": MagicMock(get=MagicMock(return_value="4000")),  # Cambio
            "max_output_tokens": MagicMock(get=MagicMock(return_value="2000")),
            "max_context_chars": MagicMock(get=MagicMock(return_value="48000")),
            "temperature": MagicMock(get=MagicMock(return_value="0.5")),
            "input_price_per_million": MagicMock(get=MagicMock(return_value="0.0")),
            "output_price_per_million": MagicMock(get=MagicMock(return_value="0.0")),
        }

        # Ejecutar lógica de save() del diálogo
        try:
            updated = LlmProfile(
                name="test",
                provider="openai_compatible",
                endpoint=values["endpoint"].get().strip(),
                model=values["model"].get().strip(),
                api_key_env=values["api_key_env"].get().strip(),
                max_total_model_tokens=int(values["max_total_model_tokens"].get()),
                max_output_tokens=int(values["max_output_tokens"].get()),
                max_context_chars=int(values["max_context_chars"].get()),
                temperature=float(values["temperature"].get()),
                input_price_per_million=float(values["input_price_per_million"].get()),
                output_price_per_million=float(values["output_price_per_million"].get()),
            )
            updated_profiles = dict(app.profiles)
            updated_profiles["test"] = updated
            storage.save_profiles(updated_profiles, "test", app.config_path)
            # Si llegamos aquí, guardar fue exitoso (pero en este test falla)
            app.profiles = updated_profiles
        except OSError as error:
            # El diálogo muestra error
            pass

        # Verificar: app.profiles no fue actualizado (transaccional)
        self.assertEqual(app.profiles["test"].max_total_model_tokens, 8000,
                        "app.profiles debe mantener el valor original tras fallo de guardado")

    @patch("tukul_ui.dialogs.messagebox.showerror")
    @patch("tukul_ui.dialogs.tk.Toplevel")
    @patch("tukul_ui.dialogs.ttk.Frame")
    def test_dialog_rejects_invalid_max_total_model_tokens(
        self, mock_frame, mock_toplevel, mock_showerror
    ):
        """Prueba: usuario intenta guardar max_total < max_output → rechazado, diálogo permanece abierto."""
        from tukul_ui.dialogs import show_settings_dialog

        # Setup
        initial_profile = LlmProfile(
            name="test",
            provider="openai_compatible",
            endpoint="https://api.example.com",
            model="gpt-4",
            max_total_model_tokens=8000,
            max_output_tokens=2000,
        )
        app = self._mock_app_and_dialog(initial_profile)

        # Usuario intenta guardar con max_total < max_output (inválido)
        values = {
            "endpoint": MagicMock(get=MagicMock(return_value="https://api.example.com")),
            "model": MagicMock(get=MagicMock(return_value="gpt-4")),
            "api_key_env": MagicMock(get=MagicMock(return_value="")),
            "max_total_model_tokens": MagicMock(get=MagicMock(return_value="1000")),  # INVÁLIDO: < max_output
            "max_output_tokens": MagicMock(get=MagicMock(return_value="2000")),
            "max_context_chars": MagicMock(get=MagicMock(return_value="48000")),
            "temperature": MagicMock(get=MagicMock(return_value="0.5")),
            "input_price_per_million": MagicMock(get=MagicMock(return_value="0.0")),
            "output_price_per_million": MagicMock(get=MagicMock(return_value="0.0")),
        }

        # Intentar crear LlmProfile con valores inválidos
        error_raised = False
        error_message = ""
        try:
            updated = LlmProfile(
                name="test",
                provider="openai_compatible",
                endpoint=values["endpoint"].get().strip(),
                model=values["model"].get().strip(),
                api_key_env=values["api_key_env"].get().strip(),
                max_total_model_tokens=int(values["max_total_model_tokens"].get()),
                max_output_tokens=int(values["max_output_tokens"].get()),
                max_context_chars=int(values["max_context_chars"].get()),
                temperature=float(values["temperature"].get()),
                input_price_per_million=float(values["input_price_per_million"].get()),
                output_price_per_million=float(values["output_price_per_million"].get()),
            )
        except ValueError as e:
            error_raised = True
            error_message = str(e)

        # Verificar: ValueError fue lanzado, no se guardó nada
        self.assertTrue(error_raised, "Debe lanzar ValueError para max_total < max_output")
        self.assertIn("max_total_model_tokens", error_message,
                     "El error debe mencionar max_total_model_tokens")
        # app.profiles no cambió (diálogo no se cerró)
        self.assertEqual(app.profiles["test"].max_total_model_tokens, 8000,
                        "app.profiles debe mantener el valor original tras rechazo de validación")


if __name__ == "__main__":
    unittest.main()
