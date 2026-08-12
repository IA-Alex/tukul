from __future__ import annotations

import math
import os
import re
import threading
from collections import Counter
from pathlib import Path

TEXT_EXTENSIONS = {".md", ".txt"}
EXCLUDED = {".git", ".codex", ".agents", "articulador", "plugins", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}
MAX_INDEXED_FILES = 500
MAX_INDEXED_FILE_BYTES = 50_000
MAX_CONTEXT_FILES = 4
FALLBACK_CONTEXT_FILES = 3
MAX_CONTEXT_PACKET_CHARS = 12_000
MAX_CONTEXT_EXCERPT_CHARS = 3_000
BM25_K1 = 1.5
BM25_B = 0.75


class ContextIndex:
    """Índice BM25 local con caché incremental y límites de memoria."""

    def __init__(self, root: Path, max_files: int = MAX_INDEXED_FILES, max_file_bytes: int = MAX_INDEXED_FILE_BYTES) -> None:
        self.root = root.resolve()
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.files: list[tuple[Path, str]] = []
        self.signature: tuple[tuple[str, int, int], ...] = ()
        self.term_frequencies: list[Counter[str]] = []
        self.document_frequency: Counter[str] = Counter()
        self.average_length = 0.0
        self.last_reasons: dict[str, str] = {}
        self._cache: dict[str, tuple[tuple[int, int], str, Counter[str]]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        stopwords = {"de", "la", "el", "en", "un", "una", "y", "o", "a", "al", "del", "es", "se", "lo", "le", "mi", "tu", "su", "no", "si"}
        return [term for term in re.findall(r"[\wáéíóúüñ]{2,}", text.lower()) if term not in stopwords]

    def _signature(self) -> tuple[tuple[str, int, int], ...]:
        result = []
        try:
            for directory, children, names in os.walk(self.root, topdown=True, onerror=lambda _error: None):
                # Podar evita incluso entrar en árboles grandes e irrelevantes.
                children[:] = [name for name in children if name not in EXCLUDED and not name.startswith(".")]
                base = Path(directory)
                for name in names:
                    path = base / name
                    if path.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        # Resolver symlinks y verificar que continúen bajo root
                        resolved = path.resolve()
                        if not resolved.is_relative_to(self.root):
                            continue  # Rechazar archivos fuera del workspace
                        relative, stat = resolved.relative_to(self.root), resolved.stat()
                        result.append((relative.as_posix(), stat.st_mtime_ns, stat.st_size))
                    except (OSError, ValueError):
                        continue
        except OSError:
            return ()
        return tuple(sorted(result)[:self.max_files])

    def refresh(self) -> None:
        with self._lock:
            self._refresh_unlocked()

    def _refresh_unlocked(self) -> None:
        signature = self._signature()
        active_names = {name for name, _mtime, _size in signature}
        next_cache: dict[str, tuple[tuple[int, int], str, Counter[str]]] = {}
        for name, modified, size in signature:
            fingerprint = (modified, size)
            cached = self._cache.get(name)
            if cached and cached[0] == fingerprint:
                next_cache[name] = cached
                continue
            try:
                # No usar read_bytes()[:n]: esa expresión carga el archivo entero
                # antes de recortarlo. Así el límite protege memoria e I/O.
                file_path = (self.root / name).resolve()
                # Verificar nuevamente que el archivo resuelto está dentro de root
                if not file_path.is_relative_to(self.root):
                    continue  # Rechazar symlinks que apunten fuera
                with file_path.open("rb") as source:
                    raw = source.read(self.max_file_bytes)
                content = raw.decode("utf-8", errors="replace")
            except (OSError, ValueError):
                continue
            frequency = Counter(self._tokens(f"{Path(name).name} {content}"))
            next_cache[name] = (fingerprint, content, frequency)

        # Eliminar las entradas de archivos borrados al reemplazar la caché completa.
        self._cache = {name: value for name, value in next_cache.items() if name in active_names}
        self.signature = signature
        self.files = [(self.root / name, value[1]) for name, value in self._cache.items()]
        self.term_frequencies = [value[2] for value in self._cache.values()]
        self.document_frequency = Counter()
        lengths = []
        for frequency in self.term_frequencies:
            self.document_frequency.update(frequency.keys())
            lengths.append(sum(frequency.values()))
        self.average_length = sum(lengths) / len(lengths) if lengths else 0.0

    def packet(self, query: str, limit: int, excluded: set[str] | None = None) -> tuple[str, list[str]]:
        with self._lock:
            if not self.files or self.signature != self._signature():
                self._refresh_unlocked()
            terms = set(self._tokens(query))
            ranked = []
            total = len(self.files)
            for index, (path, content) in enumerate(self.files):
                name = path.relative_to(self.root).as_posix().lower()
                frequency = self.term_frequencies[index]
                length = max(1, sum(frequency.values()))  # Explícito: min 1 para evitar división por cero
                score = 0.0
                for term in terms:
                    if term not in frequency:
                        continue
                    idf = math.log(1 + (total - self.document_frequency[term] + 0.5) / (self.document_frequency[term] + 0.5))
                    score += idf * (frequency[term] * (BM25_K1 + 1)) / (frequency[term] + BM25_K1 * (1 - BM25_B + BM25_B * length / max(self.average_length, 1)))
                    if term in name:
                        score += idf * 2
                ranked.append((score, path, content))
            excluded = excluded or set()
            # Sortear por score y nombre (sin crear lista intermedia de rutas relativas)
            sorted_ranked = sorted(ranked, key=lambda item: (item[0], item[1].name.lower()), reverse=True)
            # Filtrar excluidos Y calcular relative on-demand (evita duplicación de memoria)
            permitted = [(score, path, content) for score, path, content in sorted_ranked
                        if path.relative_to(self.root).as_posix() not in excluded]
            selected = [item for item in permitted if item[0] > 0][:MAX_CONTEXT_FILES] or permitted[:FALLBACK_CONTEXT_FILES]
            remaining, parts, used = min(limit, MAX_CONTEXT_PACKET_CHARS), [], []
            self.last_reasons = {}
            for score, path, content in selected:
                relative = path.relative_to(self.root).as_posix()
                if remaining <= 0:
                    break
                excerpt = content[:min(MAX_CONTEXT_EXCERPT_CHARS, remaining)]
                parts.append(f"ARCHIVO LOCAL: {relative}\n---\n{excerpt}")
                used.append(relative)
                remaining -= len(excerpt)
                # Agregar razón (diferenciada para fallback)
                if score > 0:
                    self.last_reasons[relative] = "Coincidencia BM25 con tu consulta"
                else:
                    self.last_reasons[relative] = "Fallback (sin coincidencias relevantes)"
            return "\n\n".join(parts), used
