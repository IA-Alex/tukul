from __future__ import annotations

import json
import os
import stat
import tempfile
import tomllib
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

from .logging_config import setup_logging
from .models import ArticleSession, ChatMessage, LlmProfile

logger = setup_logging()

# Optional dependencies (may be None if not installed)
keyring: Any = None
tomli_w: Any = None

try:
    import keyring as keyring_module
    keyring = keyring_module
except ImportError:
    pass

try:
    import tomli_w as tomli_w_module
    tomli_w = tomli_w_module
except ImportError:
    pass

CONFIG_PATH = Path.home() / ".config" / "articulador" / "config.toml"
def credential_backend() -> str:
    return "llavero del sistema" if keyring is not None else "solo sesión (instala keyring para recordar la key)"


def _fsync_directory(directory: Path) -> None:
    """Persiste la entrada de directorio para que el os.replace sobreviva a un corte.

    Best-effort: hay sistemas de archivos que no permiten abrir el directorio.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    """Escribe `content` en `path` de forma atómica, sin dejar parciales.

    API pública de persistencia: `DocumentManager` la usa para guardar el
    artículo y el proyecto. Era `_atomic_write` (privado), pero otro módulo la
    consumía a diario, rompiendo el contrato del guion bajo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        # mkstemp crea el temporal con 0600. Sin heredar los permisos del destino,
        # cada guardado degradaba un artículo 0644 a 0600 (y rompía compartición).
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            mode = None
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _fsync_directory(path.parent)


_STRING_FIELDS = ("provider", "endpoint", "model", "api_key_env")
_INT_FIELDS = ("max_output_tokens", "max_context_chars", "max_total_model_tokens")
_FLOAT_FIELDS = ("temperature", "input_price_per_million", "output_price_per_million")


def _coerce_profile_fields(raw: dict, allowed: set[str]) -> dict[str, int | float | str]:
    """Filtra un perfil crudo del TOML a campos conocidos y del tipo correcto."""
    kwargs: dict[str, int | float | str] = {}
    for key in allowed:
        if key == "name" or key not in raw:
            continue
        value = raw[key]
        if key in _STRING_FIELDS:
            if isinstance(value, str):
                kwargs[key] = value
        elif key in _INT_FIELDS:
            if isinstance(value, int):
                kwargs[key] = value
        elif key in _FLOAT_FIELDS:
            if isinstance(value, (int, float)):
                kwargs[key] = float(value)
    return kwargs


def _declared_active_profile(data: dict) -> str:
    """Nombre del perfil activo declarado en el TOML, o 'default' si no es usable."""
    try:
        active = data.get("llm", {}).get("active_profile", "default")
    except Exception:
        return "default"
    if not isinstance(active, str) or active not in data.get("profiles", {}):
        return "default"
    return active


def load_profiles(path: Path | str = CONFIG_PATH) -> tuple[dict[str, LlmProfile], str]:
    """Carga perfiles LLM de forma defensiva. Nunca falla; usa defaults si hay problemas.

    Args:
        path: Path to config file (Path object or string)
    """
    path = Path(path) if isinstance(path, str) else path
    profiles = {"default": LlmProfile()}
    active = "default"

    if not path.exists():
        return profiles, active

    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except Exception:
        # TOML corrupto o ilegible: usar defaults sin crash
        logger.warning("No se pudo leer config.toml. Usando defaults.")
        return profiles, active

    if not isinstance(data, dict):
        return profiles, active

    # Obtener perfil activo
    active = _declared_active_profile(data)

    # Cargar perfiles con validación defensiva
    allowed = {field.name for field in dataclass_fields(LlmProfile)}
    for name, raw in data.get("profiles", {}).items():
        if not isinstance(raw, dict) or not isinstance(name, str):
            continue
        try:
            kwargs = _coerce_profile_fields(raw, allowed)
            profiles[name] = LlmProfile(name=name, **kwargs)  # type: ignore[arg-type]
        except Exception as error:
            # Perfil individual corrupto: ignorar y continuar, pero dejar rastro.
            # Antes desaparecía en silencio y el usuario veía "sin configurar".
            logger.warning("Perfil '%s' ignorado por configuración inválida: %s", name, error)
            continue

    if active not in profiles:
        logger.warning("Perfil activo '%s' no disponible; se usa 'default'.", active)
        active = "default"
    return profiles, active


def save_profiles(
    profiles: dict[str, LlmProfile], active: str, path: Path | str = CONFIG_PATH
) -> None:
    """Save profiles to TOML file.

    Args:
        profiles: Dict of LLM profiles
        active: Name of active profile
        path: Path to config file (Path object or string)
    """
    path = Path(path) if isinstance(path, str) else path
    if tomli_w is None:
        raise RuntimeError("tomli-w no está instalado. Ejecuta: pip install tomli-w")
    # Usar dinámicamente todos los campos excepto 'name' (que ya está en la clave)
    field_names = {field.name for field in dataclass_fields(LlmProfile) if field.name != "name"}
    payload: dict[str, Any] = {"llm": {"active_profile": active}, "profiles": {}}
    for name, profile in sorted(profiles.items()):
        payload["profiles"][name] = {field: getattr(profile, field) for field in field_names}
    atomic_write(path, tomli_w.dumps(payload))


def load_key(profile: str) -> str:
    if keyring is None:
        return ""
    try:
        return keyring.get_password("articulador", profile) or ""
    except Exception:
        return ""


def save_key(profile: str, key: str) -> None:
    if keyring is None:
        raise RuntimeError("No hay llavero disponible. Instala keyring para recordar la key; de otro modo se usará solo durante esta sesión.")
    try:
        keyring.set_password("articulador", profile, key)
    except Exception as error:
        raise RuntimeError("El llavero del sistema no pudo guardar la key.") from error


def delete_key(profile: str) -> None:
    """Revoca la credencial guardada. Silenciosa si no hay llavero o no existe entrada."""
    if keyring is None:
        return
    try:
        keyring.delete_password("articulador", profile)
    except Exception:
        # keyring lanza PasswordDeleteError cuando no había nada guardado: no es un fallo.
        pass


def save_project(session: ArticleSession, path: Path) -> None:
    if session.document_path is None:
        raise ValueError("Guarda primero el artículo Markdown.")
    base = path.parent.resolve()

    def make_relative(value: Path) -> str:
        """Ruta relativa al proyecto; el destino debe contener al artículo."""
        try:
            return Path(value).resolve().relative_to(base).as_posix()
        except ValueError as error:
            raise ValueError(
                "El proyecto debe guardarse en la carpeta del artículo o en una "
                f"carpeta superior.\nArtículo: {value}\nCarpeta elegida: {base}"
            ) from error

    data = {
        "version": 2,
        "document": make_relative(session.document_path),
        "conversation": [{"role": item.role, "content": item.content} for item in session.conversation[-30:]],
    }
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _validate_relative_path(path_str: str, base_dir: Path) -> Path:
    """Valida que una ruta sea relativa y descendiente del directorio base (cross-platform).

    Raises ValueError si la ruta es absoluta o intenta escapar del directorio base.
    """
    if not path_str:
        raise ValueError("Ruta no puede estar vacía.")

    # Detectar rutas absolutas de forma cross-platform usando pathlib
    path_obj=Path(path_str)
    if path_obj.is_absolute():
        raise ValueError(f"Ruta no puede ser absoluta: {path_str}")

    # Resuelve la ruta contra el base directory
    resolved=(base_dir / path_str).resolve()
    base_resolved=base_dir.resolve()

    # Verifica que el resultado sea descendiente de base_dir
    try:
        resolved.relative_to(base_resolved)
    except ValueError as e:
        raise ValueError(f"Ruta intenta escapar del directorio del proyecto: {path_str}") from e

    return resolved


def _validated_conversation(raw: object) -> list[ChatMessage]:
    """Convierte la conversación cruda del JSON en ChatMessage, descartando basura."""
    if not isinstance(raw, list):
        return []
    conversation: list[ChatMessage] = []
    for item in raw:
        if not isinstance(item, dict) or "role" not in item or "content" not in item:
            continue
        role, content = item["role"], item["content"]
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        if role not in {"user", "assistant"}:
            continue
        try:
            conversation.append(ChatMessage(role=role, content=content))
        except (TypeError, ValueError):
            continue  # ChatMessage rechazó los valores; ignorar este item
    return conversation


def load_project(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "document" not in data:
        raise ValueError("Proyecto no válido.")

    # Validar tipos de campos críticos
    if not isinstance(data["document"], str):
        raise ValueError("Proyecto no válido: 'document' debe ser string.")

    conversation = _validated_conversation(data.get("conversation", []))

    base = path.parent
    try:
        data["document"] = _validate_relative_path(data["document"], base)
    except ValueError as e:
        raise ValueError(f"Seguridad: {e}") from e
    data["conversation"] = conversation
    return data
