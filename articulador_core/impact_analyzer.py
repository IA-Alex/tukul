"""Analizador de impacto para sugerencias basadas en fuentes oficiales.

Implementa:
- **FoggEngine**: aplica Fogg Behavior Model sobre FeedEntry[].
- **ConflictDetector**: detecta contradicciones entre fuentes.
- **SuggestionGenerator**: construye prompt y parsea respuesta a
  ConsumerSuggestion vía el LLM existente.
- **PostValidator**: verifica sin psicofancia, validación vacía ni
  incoherencias.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from articulador_core.logging_config import setup_logging
from articulador_core.models import (
    ConsumerSuggestion,
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

        has_patches = any(
            "patch" in ref.lower() or "fix" in ref.lower()
            for e in entries for ref in e.raw_references
        )
        ability: dict[str, float] = {}
        if has_patches:
            ability["parche_disponible"] = 0.8
        if not ability:
            ability["investigacion_requerida"] = 0.3

        triggers: list[str] = []
        if has_kev:
            triggers.append("Explotación activa confirmada por CISA")
        if has_high_epss:
            triggers.append("Alta probabilidad de explotación (EPSS)")
        if max_sev is not None and max_sev >= 9.0:
            triggers.append("Severidad crítica (CVSS >= 9.0)")
        if max_sev is not None and max_sev >= 7.0:
            triggers.append("Severidad alta (CVSS >= 7.0)")

        parts: list[str] = []
        if max_sev is not None:
            parts.append(f"Severidad máxima: {max_sev}/10")
        if has_kev:
            parts.append("en catálogo KEV (explotación activa)")
        if has_high_epss:
            parts.append("alta probabilidad de explotación")
        summary = ". ".join(parts) if parts else "Análisis basado en datos disponibles."

        return FoggAnalysis(
            motivation=motivation, ability=ability,
            triggers=tuple(triggers), summary=summary,
        )


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
