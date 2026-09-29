from __future__ import annotations
import json
from pathlib import Path
from articulador_core import storage

class UIStateManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.state = storage.load_ui_state(config_path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.state[key] = value
        storage.save_ui_state(self.config_path, self.state)

    def save_all(self) -> None:
        storage.save_ui_state(self.config_path, self.state)
