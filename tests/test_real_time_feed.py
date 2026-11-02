"""Tests para `tukul_core.real_time_feed` e `impact_analyzer`.

Cubre:
- Dataclasses de modelos (FeedEntry, FoggAnalysis, SourceConflict,
  ConsumerSuggestion)
- FeedCache (TTL, persistencia, desalojo)
- FeedNormalizer (deduplicación, filtrado, enriquecimiento)
- FoggEngine (análisis con datos insuficientes, casos borde)
- ConflictDetector (sin contradicciones, con contradicciones)
- PostValidator (psicofancia, validaciones vacías, casos válidos)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tukul_core.impact_analyzer import (
    ConflictDetector,
    FoggEngine,
    PostValidator,
    SuggestionGenerator,
)
from tukul_core.models import (
    ConsumerSuggestion,
    FeedEntry,
    FeedSource,
    FoggAnalysis,
    SourceConflict,
)
from tukul_core.real_time_feed import FeedCache, FeedNormalizer

# ─── Tests de dataclasses ──────────────────────────────────────────────────

class TestFeedSource:
    def test_minimal(self):
        s = FeedSource(id="nvd", label="NVD", type="cve",
                       base_url="https://nvd.nist.gov",
                       requires_api_key=False,
                       refresh_interval_minutes=60)
        assert s.id == "nvd"
        assert s.type == "cve"
        assert not s.requires_api_key

    def test_frozen(self):
        s = FeedSource(id="x", label="X", type="paper",
                       base_url="http://x.com",
                       requires_api_key=True,
                       refresh_interval_minutes=10)
        with pytest.raises(AttributeError):
            s.id = "y"  # type: ignore[misc]


class TestFeedEntry:
    def test_minimal(self):
        now = datetime.now(UTC)
        e = FeedEntry(source_id="nvd:CVE-2026-12345", source="nvd",
                      title="CVE-2026-12345",
                      description="Test vulnerability",
                      url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345",
                      published=now)
        assert e.source_id == "nvd:CVE-2026-12345"
        assert e.severity is None
        assert e.confidence == 1.0
        assert e.tags == frozenset()

    def test_full(self):
        now = datetime.now(UTC)
        e = FeedEntry(source_id="nvd:CVE-2026-99999", source="nvd",
                      title="CVE-2026-99999", description="Critical vuln",
                      url="https://nvd.nist.gov/vuln/detail/CVE-2026-99999",
                      published=now, severity=9.8, confidence=0.95,
                      topics=("ciberseguridad", "cve"),
                      tags=frozenset({"cve", "alta_criticidad"}),
                      raw_references=("https://example.com",))
        assert e.severity == 9.8
        assert "alta_criticidad" in e.tags
        assert len(e.raw_references) == 1

    def test_frozen(self):
        now = datetime.now(UTC)
        e = FeedEntry(source_id="x", source="nvd", title="x",
                      description="x", url="x", published=now)
        with pytest.raises(AttributeError):
            e.source_id = "y"  # type: ignore[misc]


class TestFoggAnalysis:
    def test_minimal(self):
        fa = FoggAnalysis(motivation={"urgencia": 0.8},
                          ability={"parche_disponible": 0.6},
                          triggers=("alerta activa",))
        assert fa.motivation["urgencia"] == 0.8
        assert fa.triggers == ("alerta activa",)
        assert fa.summary == ""

    def test_frozen(self):
        fa = FoggAnalysis(motivation={}, ability={}, triggers=())
        with pytest.raises(AttributeError):
            fa.motivation = {"x": 1.0}  # type: ignore[misc]


class TestSourceConflict:
    def test_minimal(self):
        sc = SourceConflict(sources=("nvd", "epss"), field="severity",
                            description="CVSS vs EPSS diff > 5")
        assert sc.severity == "warning"
        assert sc.field == "severity"

    def test_frozen(self):
        sc = SourceConflict(sources=("a",), field="f", description="d")
        with pytest.raises(AttributeError):
            sc.field = "other"  # type: ignore[misc]


class TestConsumerSuggestion:
    def test_minimal(self):
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(id="suggestion:abc123",
                                source_entries=("nvd:CVE-2026-12345",),
                                title="Test", rationale="Rationale",
                                fogg=fogg,
                                suggested_article_focus="Focus",
                                target_audience="tecnicos",
                                impact_level="alto",
                                uncertainty="Alta certidumbre")
        assert cs.id == "suggestion:abc123"
        assert cs.target_audience == "tecnicos"
        assert cs.impact_level == "alto"
        assert cs.disclaimer.startswith("Basado en fuentes oficiales")

    def test_default_disclaimer(self):
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(id="s:1", source_entries=(),
                                title="t", rationale="r", fogg=fogg,
                                suggested_article_focus="f",
                                target_audience="publico general",
                                impact_level="bajo", uncertainty="u")
        assert "no constituye consejo profesional" in cs.disclaimer


# ─── Tests de FeedCache ────────────────────────────────────────────────────

class TestFeedCache:
    def test_get_miss(self, tmp_path: Path) -> None:
        cache = FeedCache(tmp_path / "cache.json", ttl_minutes=15)
        assert cache.get("nvd") is None

    def test_set_and_get(self, tmp_path: Path) -> None:
        cache = FeedCache(tmp_path / "cache.json", ttl_minutes=15)
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now)]
        cache.set("nvd", entries)
        retrieved = cache.get("nvd")
        assert retrieved is not None
        assert len(retrieved) == 1
        assert retrieved[0].source_id == "nvd:CVE-1"

    def test_ttl_expiry(self, tmp_path: Path) -> None:
        cache = FeedCache(tmp_path / "cache.json", ttl_minutes=0)
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now)]
        cache.set("nvd", entries)
        time.sleep(0.1)
        assert cache.get("nvd") is None

    def test_invalidate(self, tmp_path: Path) -> None:
        cache = FeedCache(tmp_path / "cache.json", ttl_minutes=15)
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now)]
        cache.set("nvd", entries)
        cache.invalidate("nvd")
        assert cache.get("nvd") is None

    def test_clear(self, tmp_path: Path) -> None:
        cache = FeedCache(tmp_path / "cache.json", ttl_minutes=15)
        now = datetime.now(UTC)
        for sid in ("nvd", "epss"):
            cache.set(sid, [FeedEntry(source_id=f"{sid}:CVE-1",
                         source=sid, title="CVE-1",
                         description="d", url="u", published=now)])
        cache.clear()
        assert cache.get("nvd") is None
        assert cache.get("epss") is None

    def test_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache1 = FeedCache(path, ttl_minutes=15)
        now = datetime.now(UTC)
        cache1.set("nvd", [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                                     title="CVE-1", description="d",
                                     url="u", published=now)])
        cache2 = FeedCache(path, ttl_minutes=15)
        retrieved = cache2.get("nvd")
        assert retrieved is not None
        assert retrieved[0].source_id == "nvd:CVE-1"
# ─── Tests de FeedNormalizer ───────────────────────────────────────────────

class TestFeedNormalizer:
    def test_empty(self):
        n = FeedNormalizer()
        assert n.normalize_all({}) == []

    def test_deduplication(self):
        n = FeedNormalizer()
        now = datetime.now(UTC)
        result = n.normalize_all({
            "nvd": [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                              title="CVE-1", description="d", url="u",
                              published=now)],
            "epss": [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                               title="CVE-1", description="d", url="u",
                               published=now)],
        })
        assert len(result) == 1

    def test_ordering_by_severity(self):
        n = FeedNormalizer()
        now = datetime.now(UTC)
        result = n.normalize_all({
            "nvd": [
                FeedEntry(source_id="nvd:CVE-1", source="nvd",
                          title="CVE-1", description="d", url="u",
                          published=now, severity=5.0),
                FeedEntry(source_id="nvd:CVE-2", source="nvd",
                          title="CVE-2", description="d", url="u",
                          published=now, severity=9.0),
            ],
        })
        assert result[0].source_id == "nvd:CVE-2"

    def test_enrich_nvd_with_epss_and_kev(self):
        n = FeedNormalizer()
        now = datetime.now(UTC)
        nvd = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                         title="CVE-1", description="d", url="u",
                         published=now, severity=7.5)]
        epss = [FeedEntry(source_id="epss:CVE-1", source="epss",
                          title="EPSS CVE-1", description="d", url="u",
                          published=now, severity=9.5)]
        kev = [FeedEntry(source_id="kev:CVE-1", source="kev",
                         title="KEV CVE-1", description="d", url="u",
                         published=now)]
        enriched = n.enrich_nvd_with_epss_and_kev(nvd, epss, kev)
        assert "alta_probabilidad_explotacion" in enriched[0].tags
        assert "explotacion_activa" in enriched[0].tags

    def test_filter_by_topics(self):
        n = FeedNormalizer()
        now = datetime.now(UTC)
        entries = [
            FeedEntry(source_id="nvd:CVE-1", source="nvd", title="CVE-1",
                      description="d", url="u", published=now,
                      topics=("ciberseguridad", "cve")),
            FeedEntry(source_id="arxiv:123", source="arxiv", title="Paper",
                      description="d", url="u", published=now,
                      topics=("investigacion", "seguridad")),
        ]
        filtered = n.filter_by_topics(entries, {"ciberseguridad"})
        assert len(filtered) == 1
        assert filtered[0].source == "nvd"
# ─── Tests de FoggEngine ───────────────────────────────────────────────────

class TestFoggEngine:
    def test_empty_entries(self):
        engine = FoggEngine()
        result = engine.analyze([])
        assert result.motivation == {}
        assert result.ability == {}
        assert result.triggers == ()

    def test_high_severity(self):
        engine = FoggEngine()
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now, severity=9.8)]
        result = engine.analyze(entries)
        assert result.motivation.get("urgencia", 0) == pytest.approx(0.98, rel=0.01)

    def test_kev_tag_triggers_exploitacion_activa(self):
        engine = FoggEngine()
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="kev:CVE-1", source="kev",
                             title="KEV CVE-1", description="d", url="u",
                             published=now,
                             tags=frozenset({"kev", "cve", "explotacion_activa"}))]
        result = engine.analyze(entries)
        assert result.motivation.get("explotacion_activa", 0) == 0.9
        assert "Explotación activa confirmada por CISA" in result.triggers

    def test_patch_available_in_ability(self):
        engine = FoggEngine()
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now, severity=5.0,
                             raw_references=("https://example.com/patch",))]
        result = engine.analyze(entries)
        assert result.ability.get("parche_disponible", 0) == 0.8


# ─── Tests de ConflictDetector ─────────────────────────────────────────────

class TestConflictDetector:
    def test_no_conflicts(self):
        detector = ConflictDetector()
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now, severity=5.0)]
        assert detector.detect(entries) == []

    def test_severity_conflict(self):
        detector = ConflictDetector()
        now = datetime.now(UTC)
        entries = [
            FeedEntry(source_id="nvd:CVE-1", source="nvd", title="CVE-1",
                      description="d", url="u", published=now, severity=2.0),
            FeedEntry(source_id="epss:CVE-1", source="epss", title="EPSS CVE-1",
                      description="d", url="u", published=now, severity=9.5),
        ]
        conflicts = detector.detect(entries)
        assert len(conflicts) == 1
        assert "nvd" in conflicts[0].sources
        assert "epss" in conflicts[0].sources
        assert conflicts[0].field == "severity"

    def test_kev_without_nvd(self):
        detector = ConflictDetector()
        now = datetime.now(UTC)
        entries = [
            FeedEntry(source_id="kev:CVE-1", source="kev", title="KEV CVE-1",
                      description="d", url="u", published=now),
            FeedEntry(source_id="epss:CVE-1", source="epss", title="EPSS CVE-1",
                      description="d", url="u", published=now),
        ]
        conflicts = detector.detect(entries)
        assert len(conflicts) == 1
        assert conflicts[0].severity == "warning"

    def test_no_conflict_when_similar_scores(self):
        detector = ConflictDetector()
        now = datetime.now(UTC)
        entries = [
            FeedEntry(source_id="nvd:CVE-1", source="nvd", title="CVE-1",
                      description="d", url="u", published=now, severity=7.0),
            FeedEntry(source_id="epss:CVE-1", source="epss", title="EPSS CVE-1",
                      description="d", url="u", published=now, severity=6.0),
        ]
        assert len(detector.detect(entries)) == 0
# ─── Tests de PostValidator ────────────────────────────────────────────────

class TestPostValidator:
    def test_valid_suggestion(self):
        validator = PostValidator()
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(
            id="s:1", source_entries=("nvd:CVE-1",),
            title="Vulnerabilidad crítica en sistema X",
            rationale="Parche disponible, explotación activa.",
            fogg=fogg,
            suggested_article_focus="Actualización inmediata",
            target_audience="tecnicos",
            impact_level="alto",
            uncertainty="Alta certidumbre",
        )
        assert validator.is_valid(cs)

    def test_psycho_fantasy_detected(self):
        validator = PostValidator()
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(
            id="s:1", source_entries=("nvd:CVE-1",),
            title="Los hackers están en tu casa",
            rationale="R", fogg=fogg,
            suggested_article_focus="F",
            target_audience="publico general",
            impact_level="alto", uncertainty="U",
        )
        issues = validator.validate(cs)
        assert any("Psicofancia" in i for i in issues)

    def test_empty_validation_detected(self):
        validator = PostValidator()
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(
            id="s:1", source_entries=("nvd:CVE-1",),
            title="Buena idea revisar esto",
            rationale="Es correcto actualizar",
            fogg=fogg,
            suggested_article_focus="F",
            target_audience="publico general",
            impact_level="bajo", uncertainty="U",
        )
        issues = validator.validate(cs)
        assert any("Validación vacía" in i for i in issues)

    def test_invalid_impact_level(self):
        validator = PostValidator()
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(
            id="s:1", source_entries=("nvd:CVE-1",),
            title="T", rationale="R", fogg=fogg,
            suggested_article_focus="F",
            target_audience="publico general",
            impact_level="extremadamente_alto",
            uncertainty="U",
        )
        issues = validator.validate(cs)
        assert any("Nivel de impacto inválido" in i for i in issues)

    def test_no_source_entries(self):
        validator = PostValidator()
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        cs = ConsumerSuggestion(
            id="s:1", source_entries=(), title="T",
            rationale="R", fogg=fogg,
            suggested_article_focus="F",
            target_audience="tecnicos",
            impact_level="bajo", uncertainty="U",
        )
        issues = validator.validate(cs)
        assert any("no tiene entradas de fuentes" in i for i in issues)


# ─── Tests de SuggestionGenerator ──────────────────────────────────────────

class TestSuggestionGenerator:
    def test_generate_llm_failure(self):
        mock_llm = MagicMock(side_effect=RuntimeError("LLM falló"))
        gen = SuggestionGenerator(mock_llm)
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        assert gen.generate([], fogg, []) is None

    def test_generate_parse_invalid_json(self):
        mock_llm = MagicMock(return_value="esto no es json")
        gen = SuggestionGenerator(mock_llm)
        fogg = FoggAnalysis(motivation={}, ability={}, triggers=())
        assert gen.generate([], fogg, []) is None

    def test_generate_success(self):
        valid_json = json.dumps({
            "title": "Vuln crítica",
            "rationale": "Parche disponible",
            "suggested_article_focus": "Actualización urgente",
            "target_audience": "tecnicos",
            "impact_level": "alto",
            "uncertainty": "Alta",
        })
        mock_llm = MagicMock(return_value=valid_json)
        gen = SuggestionGenerator(mock_llm)
        now = datetime.now(UTC)
        entries = [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                             title="CVE-1", description="d", url="u",
                             published=now, severity=9.0)]
        fogg = FoggAnalysis(motivation={"urgencia": 0.9},
                            ability={"parche_disponible": 0.8},
                            triggers=("alerta",))
        result = gen.generate(entries, fogg, [])
        assert result is not None
        assert result.title == "Vuln crítica"
        assert result.target_audience == "tecnicos"
        assert result.impact_level == "alto"
