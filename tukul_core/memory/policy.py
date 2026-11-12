"""Política de lectura del corpus editorial."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryPolicy:
    """Define qué puede entrar al índice y con qué límites."""

    root: Path
    include_extensions: frozenset[str] = frozenset({".md", ".txt"})
    include_extensionless: bool = True
    max_file_bytes: int = 50_000
    max_files: int = 500
    excluded_directories: frozenset[str] = frozenset(
        {".git", ".agents", ".venv", "venv", "node_modules", "__pycache__", "plugins"}
    )
    excluded_names: frozenset[str] = frozenset({"mi_perfil.txt"})
    excluded_suffixes: frozenset[str] = frozenset({"~"})
    private_prefixes: tuple[str, ...] = ()

    def normalized(self) -> MemoryPolicy:
        """Devuelve la política con raíz absoluta y extensiones normalizadas."""
        return MemoryPolicy(
            root=self.root.expanduser().resolve(),
            include_extensions=frozenset(
                extension.lower() if extension.startswith(".") else f".{extension.lower()}"
                for extension in self.include_extensions
            ),
            include_extensionless=self.include_extensionless,
            max_file_bytes=self.max_file_bytes,
            max_files=self.max_files,
            excluded_directories=frozenset(self.excluded_directories),
            excluded_names=frozenset(self.excluded_names),
            excluded_suffixes=frozenset(self.excluded_suffixes),
            private_prefixes=tuple(self.private_prefixes),
        )

    def allows(self, relative_path: str, size_bytes: int) -> bool:
        """Indica si un archivo satisface la política de corpus."""
        path = Path(relative_path)
        if size_bytes > self.max_file_bytes or path.name in self.excluded_names:
            return False
        if any(part in self.excluded_directories for part in path.parts):
            return False
        if any(path.name.endswith(suffix) for suffix in self.excluded_suffixes):
            return False
        if any(relative_path == prefix or relative_path.startswith(f"{prefix}/")
               for prefix in self.private_prefixes):
            return False
        return path.suffix.lower() in self.include_extensions or (
            self.include_extensionless and not path.suffix
        )
