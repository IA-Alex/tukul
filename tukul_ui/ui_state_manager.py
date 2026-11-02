from __future__ import annotations

from pathlib import Path
from typing import Any

from tukul_core import storage


class UIStateManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.state = storage.load_ui_state(config_path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.state[key] = value
        storage.save_ui_state(self.state, self.config_path)

    def save_all(self) -> None:
        storage.save_ui_state(self.state, self.config_path)
