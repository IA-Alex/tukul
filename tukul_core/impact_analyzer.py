"""Analizador de impacto y generador de ideas para artículos.

Implementa:
- **FoggEngine**: aplica Fogg Behavior Model sobre FeedEntry[].
- **ConflictDetector**: detecta contradicciones entre fuentes.
- **SuggestionGenerator**: construye prompt y parsea respuesta a
  ConsumerSuggestion vía el LLM existente.
- **PostValidator**: verifica sin psicofancia, validación vacía ni
  incoherencias.
- **CorrelationEngine**: cruza entradas entre fuentes por CVE, tópicos
  y keywords (determinista, sin LLM).
- **IdeaGenerator**: genera ideas de artículo desde correlaciones,
  con reglas + LLM opcional para enriquecer.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from tukul_core.logging_config import setup_logging
from tukul_core.models import (
    ArticleIdea,
    ConsumerSuggestion,
    CorrelationGroup,
    FeedEntry,
    FoggAnalysis,
    SourceConflict,
)

logger = setup_logging()


class FoggEngine:
    """Aplica Fogg Behavior Model sobre entradas de fuentes oficiales."""

    def analyze(self, entries: list[FeedEntry]) -> FoggAnalysis:
        """Produce un análisis Fogg a partir de entradas de fuentes."""
        if not entries:
            return FoggAnalysis(
                motivation={}, ability={}, triggers=(),
                summary="No hay suficientes datos para un análisis Fogg.",
            )

        max_sev = max((e.severity for e in entries if e.severity is not None), default=None)
        has_kev = any("kev" in e.tags for e in entries)
        has_high_epss = any("alta_probabilidad_explotacion" in e.tags for e in entries)

        motivation = self._motivation(entries, max_sev, has_kev, has_high_epss)
        ability = self._ability(entries)
        triggers = self._triggers(max_sev, has_kev, has_high_epss)
        summary = self._summary(max_sev, has_kev, has_high_epss)

        return FoggAnalysis(
            motivation=motivation, ability=ability,
            triggers=tuple(triggers), summary=summary,
        )

    @staticmethod
    def _motivation(entries: list[FeedEntry], max_sev: float | None,
                    has_kev: bool, has_high_epss: bool) -> dict[str, float]:
        """Motivación: cuánto importa el riesgo observado."""
        motivation: dict[str, float] = {}
        if max_sev is not None:
            motivation["urgencia"] = min(max_sev / 10.0, 1.0)
        if has_kev:
            motivation["explotacion_activa"] = 0.9
        if has_high_epss:
            motivation["probabilidad_explotacion"] = 0.85
        cve_count = sum(1 for e in entries if "cve" in e.tags)
        if cve_count > 0 and not motivation:
            motivation["relevancia"] = 0.5
        return motivation

    @staticmethod
    def _ability(entries: list[FeedEntry]) -> dict[str, float]:
        """Capacidad: facilidad para actuar (parche disponible o no)."""
        has_patches = any(
            "patch" in ref.lower() or "fix" in ref.lower()
            for e in entries for ref in e.raw_references
        )
        ability: dict[str, float] = {}
        if has_patches:
            ability["parche_disponible"] = 0.8
        if not ability:
            ability["investigacion_requerida"] = 0.3
        return ability

    @staticmethod
    def _triggers(max_sev: float | None, has_kev: bool, has_high_epss: bool) -> list[str]:
        """Disparadores: qué evento empuja a actuar ahora."""
        triggers: list[str] = []
        if has_kev:
            triggers.append("Explotación activa confirmada por CISA")
        if has_high_epss:
            triggers.append("Alta probabilidad de explotación (EPSS)")
        if max_sev is not None and max_sev >= 9.0:
            triggers.append("Severidad crítica (CVSS >= 9.0)")
        if max_sev is not None and max_sev >= 7.0:
            triggers.append("Severidad alta (CVSS >= 7.0)")
        return triggers

    @staticmethod
    def _summary(max_sev: float | None, has_kev: bool, has_high_epss: bool) -> str:
        """Resumen legible de una línea."""
        parts: list[str] = []
        if max_sev is not None:
            parts.append(f"Severidad máxima: {max_sev}/10")
        if has_kev:
            parts.append("en catálogo KEV (explotación activa)")
        if has_high_epss:
            parts.append("alta probabilidad de explotación")
        return ". ".join(parts) if parts else "Análisis basado en datos disponibles."


class ConflictDetector:
    """Detecta contradicciones entre fuentes oficiales."""

    def detect(self, entries: list[FeedEntry]) -> list[SourceConflict]:
        """Analiza entradas en busca de contradicciones."""
        conflicts: list[SourceConflict] = []
        by_cve: dict[str, list[FeedEntry]] = {}

        for entry in entries:
            for prefix in ("nvd:", "epss:", "kev:"):
                if entry.source_id.startswith(prefix):
                    cve = entry.source_id[len(prefix):]
                    if cve.startswith("CVE-"):
                        by_cve.setdefault(cve, []).append(entry)
                    break

        for cve, group in by_cve.items():
            if len(group) < 2:
                continue
            nvd_e = [e for e in group if e.source == "nvd"]
            epss_e = [e for e in group if e.source == "epss"]
            kev_e = [e for e in group if e.source == "kev"]

            if nvd_e and epss_e:
                ns = nvd_e[0].severity
                es = epss_e[0].severity
                if ns is not None and es is not None and abs(ns - es) > 5.0:
                    conflicts.append(SourceConflict(
                        sources=("nvd", "epss"), field="severity",
                        description=f"{cve}: CVSS {ns}/10 vs EPSS {es/10:.2f}",
                        severity="info",
                    ))

            if kev_e and not nvd_e:
                conflicts.append(SourceConflict(
                    sources=("kev", "nvd"), field="impact",
                    description=f"{cve}: en KEV pero sin CVE en NVD",
                    severity="warning",
                ))

        return conflicts


class SuggestionGenerator:
    """Genera sugerencias de impacto usando el LLM existente."""

    def __init__(self, llm_callable: Any) -> None:
        self._llm = llm_callable

    def generate(
        self,
        entries: list[FeedEntry],
        fogg: FoggAnalysis,
        conflicts: list[SourceConflict],
        user_focus: str = "",
    ) -> ConsumerSuggestion | None:
        prompt = self._build_prompt(entries, fogg, conflicts, user_focus)
        try:
            raw_response = self._llm(prompt)
        except Exception as error:
            logger.error("SuggestionGenerator: LLM falló: %s", error)
            return None
        return self._parse_response(raw_response, entries)

    def _build_prompt(
        self,
        entries: list[FeedEntry],
        fogg: FoggAnalysis,
        conflicts: list[SourceConflict],
        user_focus: str,
    ) -> str:
        entries_section = "\n".join(
            f"- [{e.source}] {e.title}: {e.description[:200]}"
            f" (severidad: {e.severity or 'N/A'})"
            for e in entries[:15]
        )
        conflicts_section = ""
        if conflicts:
            conflicts_section = (
                "\nContradicciones detectadas:\n" + "\n".join(
                    f"- {c.description} (fuentes: {', '.join(c.sources)})"
                    for c in conflicts
                )
            )
        focus_section = (
            f"\nEnfoque solicitado por el usuario: {user_focus}"
            if user_focus else ""
        )

        return (
            "Eres un analista de ciberseguridad que genera sugerencias de "
            "impacto para artículos de concientización. Usas datos de "
            "fuentes oficiales exclusivamente. No inventas datos.\n\n"
            "Reglas:\n"
            "1. Cada afirmación debe tener respaldo en las fuentes.\n"
            "2. No uses frases de validación vacía ('buena idea', "
            "'es correcto', 'esto es importante').\n"
            "3. No caigas en psicofancia ('los hackers están en tu "
            "casa').\n"
            "4. Sé específico: qué vulnerabilidad, qué sistemas afecta, "
            "qué pueden hacer los lectores.\n"
            "5. Identifica la audiencia objetivo.\n"
            "6. Mide el nivel de incertidumbre.\n\n"
            "Datos de fuentes oficiales:\n"
            f"{entries_section}\n"
            f"{conflicts_section}"
            f"{focus_section}\n\n"
            "Análisis Fogg:\n"
            f"- Motivación: {fogg.motivation}\n"
            f"- Habilidad: {fogg.ability}\n"
            f"- Desencadenantes: {', '.join(fogg.triggers)}\n"
            f"- Resumen: {fogg.summary}\n\n"
            "Responde en el siguiente formato JSON:\n"
            "{\n"
            '  "title": "Título sugerido",\n'
            '  "rationale": "Por qué ahora y no antes",\n'
            '  "suggested_article_focus": "Enfoque narrativo",\n'
            '  "target_audience": "directivos|tecnicos|publico general",\n'
            '  "impact_level": "bajo|medio|alto",\n'
            '  "uncertainty": "Descripción de la certidumbre"\n'
            "}"
        )

    def _parse_response(
        self, raw: str, entries: list[FeedEntry]
    ) -> ConsumerSuggestion | None:
        json_str = raw.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1]
        if "```" in json_str:
            json_str = json_str.split("```")[0]
        json_str = json_str.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as error:
            logger.error("SuggestionGenerator: JSON inválido: %s", error)
            return None

        fogg = FoggAnalysis(motivation={}, ability={}, triggers=(),
                            summary=data.get("rationale", ""))
        source_ids = tuple(e.source_id for e in entries[:15])

        return ConsumerSuggestion(
            id=f"suggestion:{uuid.uuid4().hex[:12]}",
            source_entries=source_ids,
            title=data.get("title", "Sugerencia sin título"),
            rationale=data.get("rationale", ""),
            fogg=fogg,
            suggested_article_focus=data.get("suggested_article_focus", ""),
            target_audience=data.get("target_audience", "publico general"),
            impact_level=data.get("impact_level", "medio"),
            uncertainty=data.get("uncertainty", ""),
            generated_at=datetime.now(UTC),
        )


class PostValidator:
    """Valida que la sugerencia generada cumpla los requisitos."""

    PSYCHO_FANTASY_PHRASES = frozenset({
        "los hackers están en tu casa",
        "te están espiando ahora mismo",
        "tu información ya fue robada",
        "es cuestión de tiempo que te ataquen",
        "todos los sistemas están comprometidos",
        "no hay nada que puedas hacer",
        "el ataque es inminente",
    })

    EMPTY_VALIDATION_PHRASES = frozenset({
        "buena idea",
        "es correcto",
        "esto es importante",
        "muy importante",
        "es crucial",
        "es fundamental",
        "es necesario destacar",
    })

    def validate(self, suggestion: ConsumerSuggestion) -> list[str]:
        """Valida la sugerencia y devuelve lista de problemas."""
        issues: list[str] = []

        for phrase in self.PSYCHO_FANTASY_PHRASES:
            for field, val in [
                ("título", suggestion.title),
                ("rationale", suggestion.rationale),
                ("enfoque", suggestion.suggested_article_focus),
            ]:
                if phrase.lower() in val.lower():
                    issues.append(f"Psicofancia en {field}: '{phrase}'")

        for phrase in self.EMPTY_VALIDATION_PHRASES:
            for field, val in [
                ("título", suggestion.title),
                ("rationale", suggestion.rationale),
            ]:
                if phrase.lower() in val.lower():
                    issues.append(f"Validación vacía en {field}: '{phrase}'")

        valid_impacts = {"bajo", "medio", "alto"}
        if suggestion.impact_level not in valid_impacts:
            issues.append(
                f"Nivel de impacto inválido: '{suggestion.impact_level}'"
            )

        valid_audiences = {"directivos", "tecnicos", "publico general"}
        if suggestion.target_audience not in valid_audiences:
            issues.append(
                f"Audiencia objetivo inválida: "
                f"'{suggestion.target_audience}'"
            )

        if not suggestion.source_entries:
            issues.append(
                "La sugerencia no tiene entradas de fuentes que la respalden"
            )

        return issues

    def is_valid(self, suggestion: ConsumerSuggestion) -> bool:
        return len(self.validate(suggestion)) == 0


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
