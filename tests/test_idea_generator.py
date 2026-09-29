"""Tests para IdeaGenerator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from tonal_core.impact_analyzer import IdeaGenerator
from tonal_core.models import ArticleIdea, CorrelationGroup, FeedEntry


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


def _corr(
    corr_id: str,
    entries: tuple[FeedEntry, ...],
    sources: tuple[str, ...] = ("nvd",),
    topics: tuple[str, ...] = (),
    cve_id: str | None = None,
    relevance_score: float = 0.5,
    summary: str = "",
) -> CorrelationGroup:
    return CorrelationGroup(
        id=corr_id,
        entries=entries,
        sources=sources,
        topics=topics,
        cve_id=cve_id,
        relevance_score=relevance_score,
        summary=summary or f"Correlación de prueba ({corr_id})",
    )


class TestIdeaGenerator:
    """Suite de tests para IdeaGenerator."""

    def test_generate_empty(self) -> None:
        """Correlaciones vacías → lista vacía."""
        gen = IdeaGenerator()
        assert gen.generate([], []) == []

    def test_rule1_kev_high_severity(self) -> None:
        """Regla 1: CVE en KEV + severidad ≥ 7.0 → explotación activa."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0100", source="nvd", severity=8.5)
        e2 = _entry("kev:CVE-2026-0100", source="kev", severity=8.5)
        corr = _corr("corr:r1", (e1, e2), ("nvd", "kev"), cve_id="CVE-2026-0100")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        idea = ideas[0]
        assert idea.urgency == "inmediata"
        assert "explotación activa" in idea.reasoning.lower()
        assert idea.confidence >= 0.8
        assert idea.target_audience == "tecnicos"

    def test_rule1_critical_title(self) -> None:
        """Severidad ≥ 9.0 → título 'Alerta crítica'."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0101", source="nvd", severity=9.5)
        e2 = _entry("kev:CVE-2026-0101", source="kev", severity=9.5)
        corr = _corr("corr:r1b", (e1, e2), ("nvd", "kev"), cve_id="CVE-2026-0101")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        assert "Alerta crítica" in ideas[0].title

    def test_rule2_cve_arxiv(self) -> None:
        """Regla 2: CVE + arXiv → idea de investigación reciente."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0200", source="nvd", severity=7.5)
        e2 = _entry("arxiv:2401.11111", source="arxiv", severity=None)
        corr = _corr("corr:r2", (e1, e2), ("nvd", "arxiv"), cve_id="CVE-2026-0200")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        assert any("investigación" in i.title.lower()
                   or "investigación" in i.reasoning.lower() for i in ideas)
        assert ideas[0].confidence == 0.75

    def test_rule3_multiple_sources(self) -> None:
        """Regla 3: 3+ fuentes sin KEV → idea de tendencia."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0300", source="nvd", severity=6.0)
        e2 = _entry("epss:CVE-2026-0300", source="epss", severity=6.0)
        e3 = _entry("mitre:T1055", source="mitre-attack", severity=None,
                     topics=("defense-evasion",))
        corr = _corr("corr:r3", (e1, e2, e3), ("nvd", "epss", "mitre-attack"),
                      topics=("defense-evasion",))
        ideas = gen.generate([corr], [e1, e2, e3])
        assert len(ideas) >= 1
        dir_ideas = [i for i in ideas if i.target_audience == "directivos"]
        assert len(dir_ideas) >= 1
        assert dir_ideas[0].urgency == "media"
        assert dir_ideas[0].confidence == 0.65

    def test_rule4_arxiv_only(self) -> None:
        """Regla 4: Sólo arXiv → idea de vector emergente."""
        gen = IdeaGenerator()
        e1 = _entry("arxiv:2401.22222", source="arxiv", severity=None,
                     title="Novel side-channel attack on cloud VMs")
        e2 = _entry("arxiv:2401.33333", source="arxiv", severity=None,
                     title="New zero-day in container runtimes")
        corr = _corr("corr:r4", (e1, e2), ("arxiv",))
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        pub_ideas = [i for i in ideas if i.target_audience == "publico general"]
        assert len(pub_ideas) >= 1
        assert pub_ideas[0].confidence == 0.5

    def test_rule5_mitre_nvd(self) -> None:
        """Regla 5: MITRE + NVD → idea TTP concreto."""
        gen = IdeaGenerator()
        e1 = _entry("mitre:T1055", source="mitre-attack", severity=None,
                     topics=("defense-evasion",))
        e2 = _entry("nvd:CVE-2026-0400", source="nvd", severity=7.0)
        corr = _corr("corr:r5", (e1, e2), ("mitre-attack", "nvd"),
                      cve_id="CVE-2026-0400")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        tec_ideas = [i for i in ideas if "teoría" in i.title.lower()]
        assert len(tec_ideas) >= 1
        assert tec_ideas[0].target_audience == "tecnicos"
        assert tec_ideas[0].confidence == 0.7

    def test_top_10_correlations(self) -> None:
        """Sólo las primeras 10 correlaciones se procesan."""
        gen = IdeaGenerator()
        corrs = []
        for i in range(15):
            e1 = _entry(f"nvd:CVE-2026-{i:04d}a", source="nvd", severity=7.0)
            e2 = _entry(f"kev:CVE-2026-{i:04d}a", source="kev", severity=7.0)
            corrs.append(_corr(
                f"corr:top-{i}", (e1, e2), ("nvd", "kev"),
                cve_id=f"CVE-2026-{i:04d}a",
            ))
        ideas = gen.generate(corrs, [])
        assert len(ideas) <= 10

    def test_sorted_by_confidence(self) -> None:
        """Las ideas se ordenan por confianza descendente."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0500", source="nvd", severity=8.0)
        e2 = _entry("kev:CVE-2026-0500", source="kev", severity=8.0)
        e3 = _entry("epss:CVE-2026-0500", source="epss", severity=8.0)
        corr = _corr("corr:sort", (e1, e2, e3), ("nvd", "kev", "epss"),
                      cve_id="CVE-2026-0500")
        ideas = gen.generate([corr], [e1, e2, e3])
        for i in range(len(ideas) - 1):
            assert ideas[i].confidence >= ideas[i + 1].confidence

    def test_llm_enrichment(self) -> None:
        """LLM enrichment modifica título/ángulo/razonamiento."""
        def mock_llm(_prompt: str) -> str:
            return json.dumps({
                "title": "Título mejorado por LLM",
                "angle": "Ángulo mejorado",
                "reasoning": "Razonamiento expandido",
            })
        gen = IdeaGenerator(llm_callable=mock_llm)
        e1 = _entry("nvd:CVE-2026-0600", source="nvd", severity=8.5)
        e2 = _entry("kev:CVE-2026-0600", source="kev", severity=8.5)
        corr = _corr("corr:llm", (e1, e2), ("nvd", "kev"), cve_id="CVE-2026-0600")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        assert "LLM" in ideas[0].title or "mejorado" in ideas[0].title

    def test_llm_failure_graceful(self) -> None:
        """Fallo del LLM → idea original intacta."""
        def failing_llm(_prompt: str) -> str:
            raise ValueError("API error simulado")
        gen = IdeaGenerator(llm_callable=failing_llm)
        e1 = _entry("nvd:CVE-2026-0700", source="nvd", severity=8.5)
        e2 = _entry("kev:CVE-2026-0700", source="kev", severity=8.5)
        corr = _corr("corr:llm-fail", (e1, e2), ("nvd", "kev"),
                      cve_id="CVE-2026-0700")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        assert "explotación activa" in ideas[0].reasoning.lower()

    def test_llm_only_top_3(self) -> None:
        """Sólo las primeras 3 ideas reciben enrichment LLM."""
        call_count = 0
        def counting_llm(_prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps({"title": "E", "angle": "A", "reasoning": "R"})
        gen = IdeaGenerator(llm_callable=counting_llm)
        corrs = []
        for i in range(4):
            e1 = _entry(f"nvd:CVE-2026-{i:04d}x", source="nvd", severity=7.5)
            e2 = _entry(f"kev:CVE-2026-{i:04d}x", source="kev", severity=7.5)
            corrs.append(_corr(
                f"corr:cnt-{i}", (e1, e2), ("nvd", "kev"),
                cve_id=f"CVE-2026-{i:04d}x",
            ))
        gen.generate(corrs, [])
        assert call_count == 3, f"Se esperaban 3 llamadas LLM, se hicieron {call_count}"

    def test_multiple_rules_one_correlation(self) -> None:
        """Una correlación puede generar múltiples ideas."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0800", source="nvd", severity=8.0)
        e2 = _entry("kev:CVE-2026-0800", source="kev", severity=8.0)
        e3 = _entry("arxiv:2401.44444", source="arxiv", severity=None,
                     title="Research on CVE-2026-0800")
        corr = _corr("corr:multi", (e1, e2, e3), ("nvd", "kev", "arxiv"),
                      cve_id="CVE-2026-0800")
        ideas = gen.generate([corr], [e1, e2, e3])
        assert len(ideas) >= 2
        assert "inmediata" in {i.urgency for i in ideas}

    def test_no_llm_default_values(self) -> None:
        """Sin LLM, las ideas usan valores generados por reglas."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-0900", source="nvd", severity=8.5)
        e2 = _entry("kev:CVE-2026-0900", source="kev", severity=8.5)
        corr = _corr("corr:no-llm", (e1, e2), ("nvd", "kev"),
                      cve_id="CVE-2026-0900")
        ideas = gen.generate([corr], [e1, e2])
        assert len(ideas) >= 1
        assert "Alerta crítica" in ideas[0].title                or "Atención" in ideas[0].title

    def test_rule1_not_applied_low_severity(self) -> None:
        """Regla 1 no aplica si severidad < 7.0."""
        gen = IdeaGenerator()
        e1 = _entry("nvd:CVE-2026-1000", source="nvd", severity=5.0)
        e2 = _entry("kev:CVE-2026-1000", source="kev", severity=5.0)
        corr = _corr("corr:low", (e1, e2), ("nvd", "kev"),
                      cve_id="CVE-2026-1000")
        ideas = gen.generate([corr], [e1, e2])
        # Regla 1 no aplica, pero regla 5 (MITRE+NVD) tampoco porque no hay MITRE
        # Regla 2 (CVE+arXiv) tampoco porque no hay arXiv
        # Regla 3 necesita 3+ fuentes, regla 4 solo arXiv
        # Solo regla 1 podría aplicar pero severidad < 7
        # Sin embargo regla 5 requiere mitre+ndv
        # Este caso no debería generar ideas
        assert len(ideas) == 0
