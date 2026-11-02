"""Normalizador de entradas de fuentes oficiales.

Unifica los formatos dispares de cada adaptador a una lista de `FeedEntry`,
deduplica por `source_id`, filtra por relevancia y etiqueta por tema/tipo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tukul_core.models import FeedEntry


class FeedNormalizer:
    """Normaliza, deduplica y filtra entradas de múltiples fuentes."""

    def normalize_all(
        self,
        raw_entries: dict[str, list[FeedEntry]],
        hours: int = 24,
    ) -> list[FeedEntry]:
        """Combina entradas de múltiples fuentes en una lista única.

        Args:
            raw_entries: dict {source_id: [FeedEntry, ...]}.
            hours: Ventana temporal para filtrar entradas antiguas.

        Returns:
            Lista de FeedEntry únicos (por source_id), ordenados por
            severidad descendente.
        """
        seen: set[str] = set()
        merged: list[FeedEntry] = []
        since = datetime.now(UTC) - timedelta(hours=hours)

        for entries in raw_entries.values():
            for entry in entries:
                if entry.source_id in seen:
                    continue
                seen.add(entry.source_id)

                # Si la entrada es anterior a la ventana, saltar
                if entry.published < since:
                    continue

                merged.append(entry)

        # Ordenar: primero por severidad (None al final), luego por fecha
        merged.sort(
            key=lambda e: (
                -(e.severity if e.severity is not None else -1),
                e.published,
            ),
            reverse=False,
        )
        # La lista queda: más severos primero. Reverse=False con
        # severidad negativa ordena None al final.
        merged.sort(
            key=lambda e: -(e.severity if e.severity is not None else -1),
        )

        return merged

    def enrich_nvd_with_epss_and_kev(
        self,
        nvd_entries: list[FeedEntry],
        epss_entries: list[FeedEntry],
        kev_entries: list[FeedEntry],
    ) -> list[FeedEntry]:
        """Enriquece entradas NVD con scores EPSS y etiquetas KEV.

        Toma las entradas de NVD y les añade metadatos de EPSS y KEV
        cuando existe el mismo CVE ID en esas fuentes.
        """
        epss_map: dict[str, float] = {}
        for e in epss_entries:
            cve_id = e.source_id.replace("epss:", "")
            epss_map[cve_id] = e.severity / 10 if e.severity else 0.0

        kev_set: set[str] = set()
        for e in kev_entries:
            cve_id = e.source_id.replace("kev:", "")
            kev_set.add(cve_id)

        enriched: list[FeedEntry] = []
        for entry in nvd_entries:
            cve_id = entry.source_id.replace("nvd:", "")
            new_tags = set(entry.tags)

            if cve_id in epss_map:
                epss_score = epss_map[cve_id]
                if epss_score > 0.9:
                    new_tags.add("alta_probabilidad_explotacion")
                if epss_score > 0.5:
                    new_tags.add("probabilidad_explotacion_media")

            if cve_id in kev_set:
                new_tags.add("kev")
                new_tags.add("explotacion_activa")

            enriched.append(FeedEntry(
                source_id=entry.source_id,
                source=entry.source,
                title=entry.title,
                description=entry.description,
                url=entry.url,
                published=entry.published,
                updated=entry.updated,
                topics=entry.topics,
                severity=entry.severity,
                confidence=entry.confidence,
                raw_references=entry.raw_references,
                tags=frozenset(new_tags),
            ))

        return enriched

    def filter_by_topics(
        self,
        entries: list[FeedEntry],
        topics: set[str],
    ) -> list[FeedEntry]:
        """Filtra entradas que contengan al menos uno de los tópicos."""
        return [e for e in entries if set(e.topics) & topics]

    def filter_by_severity(
        self,
        entries: list[FeedEntry],
        min_severity: float,
    ) -> list[FeedEntry]:
        """Filtra entradas con severidad >= umbral."""
        return [e for e in entries if e.severity is not None and e.severity >= min_severity]
