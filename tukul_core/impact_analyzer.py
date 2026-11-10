"""Analizador de impacto y generador de ideas para artículos.

Implementa:
- **CorrelationEngine**: cruza entradas entre fuentes por CVE, tópicos
  y keywords (determinista, sin LLM).
- **IdeaGenerator**: genera ideas de artículo desde correlaciones,
  con reglas + LLM opcional para enriquecer.

Las clases históricas del pipeline Fogg (`FoggEngine`, `ConflictDetector`,
`SuggestionGenerator`, `PostValidator`) se retiraron: la UI nunca las consumió
y solo las sostenía su propio test. Los modelos que usaban (`FoggAnalysis`,
`SourceConflict`, `ConsumerSuggestion`) siguen en `models.py` como parte de la
API pública.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tukul_core.logging_config import setup_logging
from tukul_core.models import (
    ArticleIdea,
    CorrelationGroup,
    FeedEntry,
)

logger = setup_logging()


# ─── Correlación entre fuentes ──────────────────────────────────────────────


class CorrelationEngine:
    """Correlaciona entradas de distintas fuentes por CVE, tópicos y keywords.

    Es completamente determinista: no usa LLM. Las correlaciones se basan
    en:
    1. **CVE ID**: entradas que referencian el mismo CVE (NVD + EPSS + KEV).
    2. **Tópicos**: entradas que comparten tópicos (MITRE ATT&CK + arXiv).
    3. **Keywords**: solapamiento de términos relevantes en título/descripción.
    """

    CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,}")
    KEYWORDS = frozenset({
        "ransomware", "phishing", "malware", "zero-day", "zeroday",
        "vulnerabilidad", "exploit", "parche", "patch", "firewall",
        "inteligencia artificial", "machine learning", "LLM", "GPT",
        "datos personales", "privacidad", "brecha", "fuga",
        "autenticación", "MFA", "SSO", "cifrado", "encryption",
        "cloud", "nube", "kubernetes", "docker", "contenerizacion",
        "IoT", "OT", "industrial", "critical infrastructure",
        "blockchain", "cryptocurrency", "criptomoneda",
        "open source", "código abierto", "suministro",
    })

    def correlate(self, entries: list[FeedEntry]) -> list[CorrelationGroup]:
        """Cruza entradas y devuelve grupos de correlación ordenados por relevancia."""
        if not entries:
            return []
        groups: dict[str, CorrelationGroup] = {}
        self._correlate_by_cve(entries, groups)
        self._correlate_by_topics(entries, groups)
        self._correlate_by_keywords(entries, groups)
        result = sorted(
            groups.values(),
            key=lambda g: self._score_relevance(g).relevance_score,
            reverse=True,
        )
        # Devolver grupos con scores calculados
        return [self._score_relevance(g) for g in result]

    def _correlate_by_cve(
        self, entries: list[FeedEntry], groups: dict[str, CorrelationGroup]
    ) -> None:
        """Agrupa entradas que comparten el mismo CVE ID."""
        cve_map: dict[str, list[FeedEntry]] = {}
        for entry in entries:
            match = self.CVE_PATTERN.search(entry.source_id)
            if match:
                cve_id = match.group(0)
                cve_map.setdefault(cve_id, []).append(entry)
        for cve_id, cve_entries in cve_map.items():
            if len(cve_entries) >= 2:
                gid = CorrelationGroup.new_id()
                groups[gid] = CorrelationGroup(
                    id=gid,
                    entries=tuple(cve_entries),
                    sources=tuple(sorted({e.source for e in cve_entries})),
                    topics=tuple(sorted({
                        t for e in cve_entries for t in e.topics
                    })),
                    cve_id=cve_id,
                    summary=(
                        f"CVE {cve_id} referenciado por "
                        f"{len(cve_entries)} fuente(s): "
                        f"{', '.join(sorted({e.source for e in cve_entries}))}"
                    ),
                )

    def _correlate_by_topics(
        self, entries: list[FeedEntry], groups: dict[str, CorrelationGroup]
    ) -> None:
        """Agrupa entradas que comparten tópicos (sin CVE en común)."""
        topic_map: dict[str, list[FeedEntry]] = {}
        for entry in entries:
            if self._entry_in_any_group(entry, groups):
                continue
            for topic in entry.topics:
                topic_map.setdefault(topic, []).append(entry)
        for topic, topic_entries in topic_map.items():
            if len(topic_entries) >= 2:
                gid = CorrelationGroup.new_id()
                groups[gid] = CorrelationGroup(
                    id=gid,
                    entries=tuple(topic_entries),
                    sources=tuple(sorted({e.source for e in topic_entries})),
                    topics=(topic,),
                    summary=(
                        f"Tópico '{topic}' aparece en "
                        f"{len(topic_entries)} entrada(s): "
                        f"{', '.join(e.source_id for e in topic_entries)}"
                    ),
                )

    def _correlate_by_keywords(
        self, entries: list[FeedEntry], groups: dict[str, CorrelationGroup]
    ) -> None:
        """Agrupa entradas que comparten keywords relevantes."""
        keyword_map: dict[str, list[FeedEntry]] = {}
        for entry in entries:
            if self._entry_in_any_group(entry, groups):
                continue
            text = f"{entry.title} {entry.description}".lower()
            for kw in self.KEYWORDS:
                if kw in text:
                    keyword_map.setdefault(kw, []).append(entry)
        for kw, kw_entries in keyword_map.items():
            if len(kw_entries) >= 2:
                gid = CorrelationGroup.new_id()
                groups[gid] = CorrelationGroup(
                    id=gid,
                    entries=tuple(kw_entries),
                    sources=tuple(sorted({e.source for e in kw_entries})),
                    topics=(),
                    summary=(
                        f"Keyword '{kw}' aparece en "
                        f"{len(kw_entries)} entrada(s): "
                        f"{', '.join(e.source_id for e in kw_entries)}"
                    ),
                )

    @staticmethod
    def _entry_in_any_group(
        entry: FeedEntry, groups: dict[str, CorrelationGroup]
    ) -> bool:
        return any(entry in group.entries for group in groups.values())

    @staticmethod
    def _score_relevance(group: CorrelationGroup) -> CorrelationGroup:
        """Calcula el score de relevancia del grupo."""
        num_sources = len(group.sources)
        max_sev = max(
            (e.severity for e in group.entries if e.severity is not None),
            default=0.0,
        )
        has_kev = any("kev" in e.tags for e in group.entries)
        avg_conf = sum(e.confidence for e in group.entries) / len(group.entries)
        score = 0.0
        score += min(num_sources / 5.0, 1.0) * 0.3
        score += (max_sev / 10.0) * 0.3
        score += 0.25 if has_kev else 0.0
        score += avg_conf * 0.15
        return CorrelationGroup(
            id=group.id,
            entries=group.entries,
            sources=group.sources,
            topics=group.topics,
            cve_id=group.cve_id,
            relevance_score=round(min(score, 1.0), 3),
            summary=group.summary,
        )

# ─── Generador de ideas para artículos ──────────────────────────────────────


class IdeaGenerator:
    """Genera ideas de artículo desde correlaciones entre fuentes.

    Las ideas se extraen mediante reglas deterministas:
    - CVE en KEV + alta severidad → idea de explotación activa
    - CVE + paper arXiv relacionado → idea de investigación reciente
    - Múltiples CVEs mismo tópico → idea de tendencia
    - Paper arXiv sobre técnica novedosa → idea de vector emergente

    El LLM es opcional: si se proporciona, enriquece las ideas con
    contexto adicional. Sin LLM, las ideas son completamente basadas en
    reglas.
    """

    def __init__(self, llm_callable: Any | None = None) -> None:
        self._llm = llm_callable

    def generate(
        self,
        correlations: list[CorrelationGroup],
        all_entries: list[FeedEntry],
    ) -> list[ArticleIdea]:
        """Genera ideas de artículo desde las correlaciones.

        Args:
            correlations: Grupos de correlación ordenados por relevancia.
            all_entries: Todas las entradas (para contexto adicional).

        Returns:
            Lista de ArticleIdea ordenadas por confianza descendente.
        """
        ideas: list[ArticleIdea] = []
        for corr in correlations[:10]:
            corr_ideas = self._generate_for_correlation(corr, all_entries)
            ideas.extend(corr_ideas)
        if self._llm and ideas:
            ideas = self._enrich_with_llm(ideas[:3], all_entries)
        ideas.sort(key=lambda i: i.confidence, reverse=True)
        return ideas

    def _generate_for_correlation(
        self, corr: CorrelationGroup, all_entries: list[FeedEntry]
    ) -> list[ArticleIdea]:
        """Genera ideas para una correlación específica."""
        ideas: list[ArticleIdea] = []
        sources = set(corr.sources)
        has_kev = "kev" in sources
        has_nvd = "nvd" in sources
        has_arxiv = "arxiv" in sources
        has_mitre = "mitre-attack" in sources
        max_sev = max(
            (e.severity for e in corr.entries if e.severity is not None),
            default=None,
        )

        # Regla 1: CVE en KEV + severidad alta → explotación activa
        if has_kev and max_sev is not None and max_sev >= 7.0:
            ideas.append(ArticleIdea(
                id=ArticleIdea.new_id(),
                title=self._title_for_cve_kev(corr, max_sev),
                angle=(
                    "Esta vulnerabilidad está siendo explotada activamente "
                    "según CISA. El artículo debe explicar el impacto, los "
                    "sistemas afectados y las mitigaciones disponibles."
                ),
                supporting_entries=tuple(e.source_id for e in corr.entries),
                target_audience="tecnicos",
                urgency="inmediata",
                confidence=min(0.9, 0.5 + max_sev / 20.0),
                reasoning=(
                    f"Severidad {max_sev}/10, explotación activa confirmada "
                    f"por CISA KEV, {len(corr.sources)} fuente(s) confirman."
                ),
                correlation_id=corr.id,
            ))

        # Regla 2: CVE + paper arXiv → investigación reciente
        if has_nvd and has_arxiv and corr.cve_id:
            ideas.append(ArticleIdea(
                id=ArticleIdea.new_id(),
                title=f"Nueva investigación sobre {corr.cve_id}: "
                      f"implicaciones y mitigaciones",
                angle=(
                    "Un paper académico reciente analiza esta vulnerabilidad. "
                    "El artículo puede contrastar la visión oficial (NVD) "
                    "con los hallazgos de la investigación."
                ),
                supporting_entries=tuple(e.source_id for e in corr.entries),
                target_audience="tecnicos",
                urgency="alta" if (max_sev or 0) >= 7.0 else "media",
                confidence=0.75,
                reasoning=(
                    f"{corr.cve_id} tiene análisis tanto de NVD como de "
                    f"investigación académica (arXiv), permitiendo un "
                    f"artículo con perspectivas múltiples."
                ),
                correlation_id=corr.id,
            ))

        # Regla 3: Múltiples fuentes sin KEV → tendencia
        if len(corr.sources) >= 3 and not has_kev:
            topic_str = ", ".join(corr.topics[:3]) if corr.topics else \
                "ciberseguridad"
            ideas.append(ArticleIdea(
                id=ArticleIdea.new_id(),
                title=f"Panorama actual: {topic_str} en múltiples frentes",
                angle=(
                    f"{len(corr.sources)} fuentes distintas coinciden en "
                    f"este tema. El artículo puede ofrecer una visión "
                    f"panorámica del estado del arte."
                ),
                supporting_entries=tuple(e.source_id for e in corr.entries),
                target_audience="directivos",
                urgency="media",
                confidence=0.65,
                reasoning=(
                    f"{len(corr.sources)} fuentes independientes "
                    f"({', '.join(corr.sources)}) abordan el mismo tema."
                ),
                correlation_id=corr.id,
            ))

        # Regla 4: Paper arXiv sobre técnica/amenaza novedosa
        if has_arxiv and not has_nvd and not has_kev:
            entries_text = " | ".join(
                f"{e.title}: {e.description[:100]}"
                for e in corr.entries if e.source == "arxiv"
            )
            ideas.append(ArticleIdea(
                id=ArticleIdea.new_id(),
                title="Nuevo vector de amenaza identificado en investigación "
                      "académica",
                angle=(
                    "Investigación reciente (arXiv) señala un nuevo vector "
                    "de ataque o vulnerabilidad. El artículo debe traducir "
                    "hallazgos académicos a lenguaje accesible."
                ),
                supporting_entries=tuple(e.source_id for e in corr.entries),
                target_audience="publico general",
                urgency="media",
                confidence=0.5,
                reasoning=f"Paper(s) reciente(s): {entries_text[:200]}",
                correlation_id=corr.id,
            ))

        # Regla 5: MITRE ATT&CK + CVE → TTP concreto
        if has_mitre and has_nvd:
            ideas.append(ArticleIdea(
                id=ArticleIdea.new_id(),
                title="De la teoría a la práctica: TTP de MITRE ATT&CK "
                      "aplicado a vulnerabilidades activas",
                angle=(
                    "Vincular una técnica de MITRE ATT&CK con "
                    "vulnerabilidades reales (CVE) ayuda a los lectores "
                    "a entender el ciclo de vida del ataque."
                ),
                supporting_entries=tuple(e.source_id for e in corr.entries),
                target_audience="tecnicos",
                urgency="alta" if (max_sev or 0) >= 7.0 else "media",
                confidence=0.7,
                reasoning=(
                    "Conexión entre técnica de ataque documentada (MITRE) "
                    "y vulnerabilidad concreta (NVD/KEV)."
                ),
                correlation_id=corr.id,
            ))

        return ideas

    def _title_for_cve_kev(
        self, corr: CorrelationGroup, max_sev: float
    ) -> str:
        """Genera título descriptivo para un CVE con explotación activa."""
        cve_str = f" {corr.cve_id}" if corr.cve_id else ""
        if max_sev >= 9.0:
            return (
                f"Alerta crítica{cve_str}: vulnerabilidad bajo explotación "
                f"activa — actúa ya"
            )
        return (
            f"Atención{cve_str}: vulnerabilidad en explotación activa, "
            f"evalúa tu exposición"
        )

    def _enrich_with_llm(
        self, ideas: list[ArticleIdea], all_entries: list[FeedEntry]
    ) -> list[ArticleIdea]:
        """Usa el LLM para enriquecer las mejores ideas con contexto."""
        if not self._llm or not ideas:
            return ideas

        enriched: list[ArticleIdea] = []
        for idea in ideas:
            try:
                prompt = (
                    "Eres un editor especializado en ciberseguridad e IA. "
                    "Mejora la siguiente idea para un artículo agregando "
                    "contexto, ángulos alternativos y precisión técnica. "
                    "No inventes datos que no estén en las fuentes.\n\n"
                    f"Título actual: {idea.title}\n"
                    f"Ángulo: {idea.angle}\n"
                    f"Audiencia: {idea.target_audience}\n"
                    f"Urgencia: {idea.urgency}\n\n"
                    "Responde SOLO JSON:\n"
                    '{"title": "título mejorado", '
                    '"angle": "ángulo mejorado", '
                    '"reasoning": "razonamiento expandido"}\n'
                )
                raw = self._llm(prompt)
                data = json.loads(raw)
                enriched.append(ArticleIdea(
                    id=idea.id,
                    title=data.get("title", idea.title),
                    angle=data.get("angle", idea.angle),
                    supporting_entries=idea.supporting_entries,
                    target_audience=idea.target_audience,
                    urgency=idea.urgency,
                    confidence=idea.confidence,
                    reasoning=data.get("reasoning", idea.reasoning),
                    correlation_id=idea.correlation_id,
                ))
            except Exception as error:
                logger.warning(
                    "IdeaGenerator: LLM enrichment falló para %s: %s",
                    idea.id, error,
                )
                enriched.append(idea)

        return enriched
