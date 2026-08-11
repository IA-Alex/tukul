from __future__ import annotations

import json
import os
import tempfile
import tomllib
from dataclasses import fields as dataclass_fields
from pathlib import Path

from .logging_config import setup_logging
from .models import ArticleSession, ChatMessage, LlmProfile

logger = setup_logging()

try:
    import keyring
except ImportError:
    keyring = None
try:
    import tomli_w
except ImportError:
    tomli_w = None

CONFIG_PATH = Path.home() / ".config" / "articulador" / "config.toml"
def credential_backend() -> str:
    return "llavero del sistema" if keyring is not None else "solo sesión (instala keyring para recordar la key)"


def _atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def load_profiles(path: Path = CONFIG_PATH) -> tuple[dict[str, LlmProfile], str]:
    """Carga perfiles LLM de forma defensiva. Nunca falla; usa defaults si hay problemas."""
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
    try:
        active = data.get("llm", {}).get("active_profile", "default")
        if not isinstance(active, str) or active not in data.get("profiles", {}):
            active = "default"
    except Exception:
        pass

    # Cargar perfiles con validación defensiva
    allowed = {field.name for field in dataclass_fields(LlmProfile)}
    for name, raw in data.get("profiles", {}).items():
        if not isinstance(raw, dict) or not isinstance(name, str):
            continue
        try:
            # Solo incluir campos válidos y del tipo correcto
            kwargs = {}
            for key in allowed:
                if key == "name" or key not in raw:
                    continue
                value = raw[key]
                # Validación básica de tipos
                if key in ("provider", "endpoint", "model", "api_key_env"):
                    if isinstance(value, str):
                        kwargs[key] = value
                elif key in ("max_output_tokens", "max_context_chars", "max_total_model_tokens"):
                    if isinstance(value, int):
                        kwargs[key] = value
                elif key in ("temperature", "input_price_per_million", "output_price_per_million"):
                    if isinstance(value, (int, float)):
                        kwargs[key] = float(value)
            profiles[name] = LlmProfile(name=name, **kwargs)
        except Exception:
            # Perfil individual corrupto: ignorar y continuar
            continue

    return profiles, active if active in profiles else "default"


def save_profiles(profiles: dict[str, LlmProfile], active: str, path: Path = CONFIG_PATH) -> None:
    if tomli_w is None:
        raise RuntimeError("Falta tomli-w. Instala dependencias con: pip install -r requirements.txt")
    # Usar dinámicamente todos los campos excepto 'name' (que ya está en la clave)
    field_names = {field.name for field in dataclass_fields(LlmProfile) if field.name != "name"}
    payload = {"llm": {"active_profile": active}, "profiles": {}}
    for name, profile in sorted(profiles.items()):
        payload["profiles"][name] = {field: getattr(profile, field) for field in field_names}
    _atomic_write(path, tomli_w.dumps(payload))


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


def save_project(session: ArticleSession, path: Path) -> None:
    if session.document_path is None:
        raise ValueError("Guarda primero el artículo Markdown.")
    base = path.parent
    relative = lambda value: os.path.relpath(value, base)
    data = {
        "version": 2,
        "document": relative(session.document_path),
        "corpus": relative(session.corpus_path) if session.corpus_path else "",
        "evidence": session.evidence,
        "conversation": [{"role": item.role, "content": item.content} for item in session.conversation[-30:]],
    }
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_project(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "document" not in data:
        raise ValueError("Proyecto no válido.")

    # Validar tipos de campos críticos
    if not isinstance(data["document"], str):
        raise ValueError("Proyecto no válido: 'document' debe ser string.")

    corpus = data.get("corpus")
    if corpus is not None and not isinstance(corpus, str):
        raise ValueError("Proyecto no válido: 'corpus' debe ser string o null.")

    # Validar evidence (si es malformado, usar []). Los datos malformados se ignoran silenciosamente.
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
    data["evidence"] = evidence  # Guardar evidence validado

    # Validar conversation de forma defensiva
    conversation_raw = data.get("conversation", [])
    if not isinstance(conversation_raw, list):
        conversation_raw = []

    conversation = []
    for item in conversation_raw:
        if not isinstance(item, dict):
            continue
        # Extraer solo claves válidas y validar tipos estrictamente
        if "role" in item and "content" in item:
            role = item["role"]
            content = item["content"]

            # Validar que role y content son strings
            if not isinstance(role, str) or not isinstance(content, str):
                continue

            # Validar que role es uno de los permitidos
            if role not in {"user", "assistant"}:
                continue

            try:
                conversation.append(ChatMessage(role=role, content=content))
            except (TypeError, ValueError):
                # ChatMessage rechazó valores; ignorar este item
                continue

    base = path.parent
    data["document"] = (base / data["document"]).resolve()
    if data.get("corpus"):
        data["corpus"] = (base / data["corpus"]).resolve()
    data["conversation"] = conversation
    return data
