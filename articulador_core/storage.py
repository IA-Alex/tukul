from __future__ import annotations

import json
import os
import stat
import tempfile
import tomllib
from dataclasses import fields as dataclass_fields
from pathlib import Path, PureWindowsPath
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
    """Devuelve el backend de credenciales en uso: llavero del sistema o solo sesión."""
    return "llavero del sistema" if keyring is not None else "solo sesión (instala keyring para recordar la key)"


def estado_ui_path(config_path: Path | str = CONFIG_PATH) -> Path:
    """Ruta del estado de interfaz, junto al config de perfiles.

    Vive al lado de `config.toml` para que una instalación tenga un único
    directorio de estado y, de paso, para que los tests puedan aislarlo pasando
    un `config_path` en un directorio temporal.
    """
    return Path(config_path).with_name("estado.json")


def load_ui_state(config_path: Path | str = CONFIG_PATH) -> dict:
    """Carga el estado de interfaz de forma defensiva. Nunca falla."""
    try:
        data = json.loads(estado_ui_path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_ui_state(state: dict, config_path: Path | str = CONFIG_PATH) -> None:
    """Persiste el estado de interfaz de forma atómica."""
    atomic_write(
        estado_ui_path(config_path),
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    )


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
    """Recupera la API key del llavero; '' si no hay llavero o no existe entrada."""
    if keyring is None:
        return ""
    try:
        return keyring.get_password("articulador", profile) or ""
    except Exception:
        return ""


def save_key(profile: str, key: str) -> None:
    """Guarda la API key de un perfil en el llavero; RuntimeError si no hay llavero."""
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
    """Persiste un proyecto recuperable: ruta relativa del artículo y conversación.

    Raises ValueError si el artículo no está guardado o no queda bajo la carpeta
    elegida para el proyecto.
    """
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

    Rechaza rutas absolutas POSIX (`/tmp/...`), rutas absolutas Windows
    (`C:\\...`), rutas UNC (`\\\\server\\share\\...`) e intentos de escapar con
    `..` usando tanto `/` como `\\` como separador. Corre igual en Linux,
    Windows y macOS.

    Raises ValueError si la ruta es absoluta o intenta escapar del directorio base.
    """
    if not path_str:
        raise ValueError("Ruta no puede estar vacía.")

    # Unificar separadores: en Windows '\\' separa y en POSIX es parte del nombre.
    # Normalizar a '/' hace que la validación y la resolución sean idénticas en
    # las tres plataformas y evita que escapes estilo '..\\outside.md' pasen
    # desapercibidos en Linux (Path() los trataría como un nombre literal).
    normalized = path_str.replace("\\", "/")

    # Absolutas POSIX: empiezan con '/'. Cubre también raíces estilo '\\foo'
    # (ya normalizadas a '/foo') y UNC con doble barra '//server/share/...'.
    if normalized.startswith("/"):
        raise ValueError(f"Ruta no puede ser absoluta: {path_str}")

    # Absolutas Windows (C:\\...) y UNC (\\\\server\\share\\...): PureWindowsPath
    # las reconoce aunque el proceso corra en Linux/macOS. También se rechazan
    # prefijos de unidad estilo 'C:...' (drive-relative), que en Windows se
    # resuelven contra el directorio actual de esa unidad y no son rutas
    # relativas seguras al proyecto.
    windows_path = PureWindowsPath(path_str)
    if windows_path.is_absolute() or windows_path.drive:
        raise ValueError(f"Ruta no puede ser absoluta: {path_str}")

    # Escapes con '..' (usando '/' o '\\'): resolver contra base_dir y exigir
    # que el resultado siga siendo descendiente del proyecto.
    resolved = (base_dir / normalized).resolve()
    base_resolved = base_dir.resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as error:
        raise ValueError(
            f"Ruta intenta escapar del directorio del proyecto: {path_str}"
        ) from error

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


# Tope de lectura del archivo de proyecto: es JSON pequeño por diseño (ruta del
# artículo + hasta 30 mensajes de conversación). Sin este límite, un .json de
# proyecto corrupto o manipulado con un tamaño desmedido se cargaba entero en
# memoria antes de que cualquier validación pudiera rechazarlo.
MAX_PROJECT_BYTES = 2 * 1024 * 1024


def load_project(path: Path) -> dict:
    """Carga un proyecto validando tamaño, estructura y rutas relativas seguras."""
    size = path.stat().st_size
    if size > MAX_PROJECT_BYTES:
        raise ValueError(
            f"El proyecto pesa {size:,} bytes y supera el límite de "
            f"{MAX_PROJECT_BYTES // (1024 * 1024)} MB."
        )
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
