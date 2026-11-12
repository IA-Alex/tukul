"""Repositorio de archivos para la memoria local."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path

from tukul_core.memory.models import MemoryDocument
from tukul_core.memory.policy import MemoryPolicy

_TITLE_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


class FileMemoryRepository:
    """Lee documentos de texto bajo una raíz sin ejecutar ni seguir enlaces."""

    def __init__(self, policy: MemoryPolicy) -> None:
        self.policy = policy.normalized()

    def iter_documents(self) -> Iterator[MemoryDocument]:
        """Recorre archivos autorizados en orden estable y con límite de cantidad."""
        root = self.policy.root
        if not root.is_dir():
            return

        count = 0
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
            if count >= self.policy.max_files:
                return
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(root).as_posix()
                size = path.stat().st_size
            except OSError:
                continue
            if not self.policy.allows(relative, size):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "\x00" in content:
                continue
            stat = path.stat()
            count += 1
            yield MemoryDocument(
                document_id=hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24],
                relative_path=relative,
                title=self._title(path, content),
                category=self._category(path),
                extension=path.suffix.lower(),
                size_bytes=size,
                modified_ns=stat.st_mtime_ns,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                content=content,
            )

    def read_document(self, relative_path: str) -> MemoryDocument | None:
        """Lee un documento previamente devuelto por el índice, sin escapar de la raíz."""
        root = self.policy.root
        candidate = root / relative_path
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root)
            if not resolved.is_file() or resolved.is_symlink():
                return None
            size = resolved.stat().st_size
            if not self.policy.allows(relative_path, size):
                return None
            content = resolved.read_text(encoding="utf-8")
            if "\x00" in content:
                return None
            stat = resolved.stat()
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        return MemoryDocument(
            document_id=hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24],
            relative_path=relative_path,
            title=self._title(resolved, content),
            category=self._category(resolved),
            extension=resolved.suffix.lower(),
            size_bytes=size,
            modified_ns=stat.st_mtime_ns,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content=content,
        )

    @staticmethod
    def _title(path: Path, content: str) -> str:
        match = _TITLE_RE.search(content[:8_000])
        return match.group(1).strip() if match else path.stem.replace("_", " ")

    @staticmethod
    def _category(path: Path) -> str:
        extension = path.suffix.lower()
        if extension == ".md":
            return "article"
        if extension == ".txt":
            return "research"
        return "text"
