"""Tests para CorrelationEngine."""

from __future__ import annotations

from datetime import UTC, datetime

from tukul_core.impact_analyzer import CorrelationEngine
from tukul_core.models import FeedEntry


def _entry(
    source_id: str,
    source: str = "nvd",
    title: str = "Vulnerabilidad crítica",
    description: str = "Descripción de prueba",
    severity: float | None = 8.5,
    topics: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    confidence: float = 0.8,
) -> FeedEntry:
    return FeedEntry(
        source_id=source_id,
        source=source,
        title=title,
        description=description,
        url=f"https://example.com/{source_id}",
        severity=severity,
        published=datetime.now(UTC),
        topics=topics,
        tags=tags,
        confidence=confidence,
        raw_references=(),
    )


class TestCorrelationEngine:
    """Suite de tests para CorrelationEngine."""

    def test_correlate_empty(self) -> None:
        """Lista vacía → lista vacía."""
        engine = CorrelationEngine()
        assert engine.correlate([]) == []

    def test_correlate_single_entry(self) -> None:
        """Una sola entrada → sin grupos."""
        engine = CorrelationEngine()
        result = engine.correlate([_entry("nvd:CVE-2026-0001")])
        assert result == []

    def test_correlate_by_cve(self) -> None:
        """Dos entradas con mismo CVE → grupo CVE."""
        engine = CorrelationEngine()
        e1 = _entry("nvd:CVE-2026-0001", source="nvd")
        e2 = _entry("kev:CVE-2026-0001", source="kev")
        result = engine.correlate([e1, e2])
        assert len(result) == 1
        g = result[0]
        assert g.cve_id == "CVE-2026-0001"
        assert "nvd" in g.sources
        assert "kev" in g.sources
        assert len(g.entries) == 2

    def test_correlate_by_cve_three(self) -> None:
        """Tres entradas con mismo CVE → grupo único."""
        engine = CorrelationEngine()
        entries = [
            _entry("nvd:CVE-2026-0002", source="nvd"),
            _entry("epss:CVE-2026-0002", source="epss"),
            _entry("kev:CVE-2026-0002", source="kev"),
        ]
        result = engine.correlate(entries)
        assert len(result) == 1
        assert len(result[0].entries) == 3
        assert len(result[0].sources) == 3

    def test_correlate_by_topics(self) -> None:
        """Entradas con tópico compartido → grupo por tópico."""
        engine = CorrelationEngine()
        e1 = _entry("mitre:T1055", source="mitre-attack",
                     topics=("defense-evasion",))
        e2 = _entry("arxiv:2401.12345", source="arxiv",
                     topics=("defense-evasion",))
        result = engine.correlate([e1, e2])
        assert len(result) == 1
        assert "defense-evasion" in result[0].topics

    def test_correlate_by_keywords(self) -> None:
        """Entradas con keyword en común → grupo por keyword."""
        engine = CorrelationEngine()
        e1 = _entry("nvd:CVE-2026-0003", source="nvd",
                     title="Ransomware attack on infrastructure")
        e2 = _entry("arxiv:2401.67890", source="arxiv",
                     title="New ransomware techniques", severity=None)
        result = engine.correlate([e1, e2])
        assert len(result) >= 1
        assert any("ransomware" in g.summary for g in result)

    def test_entry_not_reused(self) -> None:
        """Entrada ya en grupo CVE no se añade a otro grupo."""
        engine = CorrelationEngine()
        e1 = _entry("nvd:CVE-2026-0004", source="nvd",
                     title="Ransomware CVE")
        e2 = _entry("kev:CVE-2026-0004", source="kev",
                     title="Ransomware KEV")
        result = engine.correlate([e1, e2])
        assert len(result) == 1
        assert result[0].cve_id == "CVE-2026-0004"

    def test_multiple_cve_groups(self) -> None:
        """Varios CVEs distintos → grupos separados."""
        engine = CorrelationEngine()
        entries = [
            _entry("nvd:CVE-2026-0010", source="nvd"),
            _entry("kev:CVE-2026-0010", source="kev"),
            _entry("nvd:CVE-2026-0011", source="nvd"),
            _entry("epss:CVE-2026-0011", source="epss"),
        ]
        result = engine.correlate(entries)
        assert len(result) == 2
        assert {g.cve_id for g in result} == {"CVE-2026-0010", "CVE-2026-0011"}

    def test_relevance_scoring(self) -> None:
        """3 fuentes + severidad 5 + KEV + conf 0.8 = score 0.7."""
        engine = CorrelationEngine()
        entries = [
            _entry("nvd:CVE-2026-0020", source="nvd", severity=5.0, tags=("kev",)),
            _entry("kev:CVE-2026-0020", source="kev", severity=5.0, tags=("kev",)),
            _entry("epss:CVE-2026-0020", source="epss", severity=5.0, tags=("kev",)),
        ]
        result = engine.correlate(entries)
        assert len(result) == 1
        assert result[0].relevance_score == 0.7

    def test_no_cve_no_topic_no_keyword(self) -> None:
        """Entradas sin CVE, tópicos ni keywords → 0 grupos."""
        engine = CorrelationEngine()
        e1 = _entry("arxiv:2401.99999", source="arxiv", severity=None,
                     title="Abstract math paper")
        e2 = _entry("arxiv:2401.99998", source="arxiv", severity=None,
                     title="Another math paper")
        assert engine.correlate([e1, e2]) == []

    def test_shared_topic_no_cve(self) -> None:
        """Entradas sin CVE pero con tópico compartido → grupo."""
        engine = CorrelationEngine()
        e1 = _entry("mitre:T1003", source="mitre-attack",
                     topics=("credential-access",), severity=None)
        e2 = _entry("arxiv:2401.54321", source="arxiv",
                     topics=("credential-access",), severity=None)
        result = engine.correlate([e1, e2])
        assert len(result) == 1
        assert "credential-access" in result[0].topics

    def test_no_cve_in_source_id(self) -> None:
        """Entradas sin patrón CVE en source_id → sin grupo CVE."""
        engine = CorrelationEngine()
        e1 = _entry("mitre:T1055", source="mitre-attack",
                     title="Defense Evasion", severity=None)
        e2 = _entry("mitre:T1003", source="mitre-attack",
                     title="Credential Access", severity=None)
        assert engine.correlate([e1, e2]) == []

    def test_result_sorted_by_relevance(self) -> None:
        """Resultados ordenados por relevancia descendente."""
        engine = CorrelationEngine()
        a1 = _entry("nvd:CVE-2026-0100", source="nvd", severity=9.0)
        a2 = _entry("kev:CVE-2026-0100", source="kev", severity=9.0)
        a3 = _entry("epss:CVE-2026-0100", source="epss", severity=9.0)
        b1 = _entry("nvd:CVE-2026-0101", source="nvd", severity=4.0)
        b2 = _entry("epss:CVE-2026-0101", source="epss", severity=4.0)
        entries = [a1, a2, a3, b1, b2]
        result = engine.correlate(entries)
        assert len(result) == 2
        assert result[0].relevance_score >= result[1].relevance_score
