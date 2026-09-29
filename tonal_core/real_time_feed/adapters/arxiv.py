"""Adaptador para arXiv API (papers académicos).

Consulta papers de ciberseguridad (cs.CR) e inteligencia artificial (cs.AI)
desde el arXiv API pública. No requiere API key.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from articulador_core.http_safety import NO_REDIRECT_OPENER
from articulador_core.models import FeedEntry

from .base import SourceAdapter

ARXIV_API_URL = "http://export.arxiv.org/api/query"
HTTP_TIMEOUT = 30
MAX_ATTEMPTS = 2
BACKOFF_BASE = 0.5
BACKOFF_MAX = 2.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
USER_AGENT = (
    "Articulador/ThreatFeed (+https://github.com/; "
    "contacto: mantenedor del repositorio)"
)
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivAdapter(SourceAdapter):
    """Consulta papers de arXiv por categoría."""

    @classmethod
    def source_id(cls) -> str:
        return "arxiv"

    @classmethod
    def label(cls) -> str:
        return "arXiv (papers académicos)"

    def fetch(self, hours: int) -> list[dict]:
        """Obtiene papers recientes de cs.CR y cs.AI."""
        all_entries: list[dict] = []
        for cat in ("cs.CR", "cs.AI"):
            entries = self._fetch_category(cat, hours)
            all_entries.extend(entries)
        return all_entries

    def _fetch_category(self, category: str, hours: int) -> list[dict]:
        """Obtiene papers de una categoría específica."""
        params = urllib.parse.urlencode({
            "search_query": f"cat:{category}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": 50,
        })
        url = f"{ARXIV_API_URL}?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = NO_REDIRECT_OPENER.open(request, timeout=HTTP_TIMEOUT)
                body = self._read_bounded(response)
                return self._parse_atom(body, category)
            except urllib.error.HTTPError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"arXiv respondió {error.code}: {error.reason}"
                ) from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar con arXiv: {error.reason}"
                ) from error
        return []

    def _parse_atom(self, body: bytes, category: str) -> list[dict]:
        """Parsea respuesta Atom XML de arXiv."""
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return []
        entries: list[dict] = []
        for entry in root.findall("atom:entry", ARXIV_NS):
            title_el = entry.find("atom:title", ARXIV_NS)
            summary_el = entry.find("atom:summary", ARXIV_NS)
            published_el = entry.find("atom:published", ARXIV_NS)
            link_el = entry.find("atom:id", ARXIV_NS)
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            summary = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
            paper_id = link_el.text.strip() if link_el is not None and link_el.text else ""
            published = published_el.text if published_el is not None else ""
            if not title or not paper_id:
                continue
            entries.append({
                "id": paper_id, "title": title, "summary": summary[:1000],
                "published": published, "category": category,
            })
        return entries

    def normalize(self, raw: list[dict]) -> list[FeedEntry]:
        """Convierte papers crudos de arXiv en FeedEntry."""
        entries: list[FeedEntry] = []
        for paper in raw:
            paper_id = paper.get("id", "")
            title = paper.get("title", "")
            summary = paper.get("summary", "")
            category = paper.get("category", "cs.CR")
            try:
                published = datetime.fromisoformat(
                    paper.get("published", "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                published = datetime.now(UTC)
            topic_label = "seguridad" if category == "cs.CR" else "inteligencia_artificial"
            entries.append(FeedEntry(
                source_id=f"arxiv:{paper_id}",
                source="arxiv",
                title=title[:200],
                description=summary[:500],
                url=paper_id,
                published=published,
                severity=None,
                confidence=0.85,
                topics=("investigacion", topic_label, "paper"),
                tags=frozenset({"arxiv", "paper", topic_label}),
            ))
        return entries

    def _read_bounded(self, response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("arXiv respuesta supera límite.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _sleep(self, attempt: int) -> None:
        delay = min(BACKOFF_BASE * (2 ** (attempt - 1)) * 1.25, BACKOFF_MAX * 1.25)
        time.sleep(delay)
