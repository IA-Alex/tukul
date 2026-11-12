"""Regresión: todas las fechas del feed deben llevar zona horaria.

Síntoma original: `FeedOrchestrator.fetch_all()` (pipeline de ideas) reventaba
con `TypeError: can't compare offset-naive and offset-aware datetimes` en
`FeedNormalizer.normalize_all`, porque NVD y CISA KEV devuelven fechas sin
sufijo de zona (`2026-11-11T22:17:10.820`, `2026-11-10`) y `fromisoformat`
producía datetimes NAIVE que luego se comparaban contra un `since` UTC.

Estas pruebas fijan el contrato en los productores (adaptadores), en el caché y
en el consumidor (normalizador), sin red.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tukul_core.models import FeedEntry
from tukul_core.real_time_feed._dates import parse_feed_date
from tukul_core.real_time_feed.adapters.kev import KevAdapter
from tukul_core.real_time_feed.adapters.nvd import _parse_nvd_date
from tukul_core.real_time_feed.cache import FeedCache, _aware_o_ahora
from tukul_core.real_time_feed.normalizer import FeedNormalizer


class TestParseFeedDate:
    """La normalización común cubre las tres variantes de las fuentes."""

    def test_sin_zona_se_asume_utc(self):
        assert parse_feed_date("2026-11-11T22:17:10.820") == datetime(
            2026, 11, 11, 22, 17, 10, 820000, tzinfo=UTC)

    def test_solo_fecha_se_asume_utc(self):
        assert parse_feed_date("2026-11-10") == datetime(2026, 11, 10, tzinfo=UTC)

    def test_con_z(self):
        assert parse_feed_date("2026-11-04T10:00:00Z") == datetime(
            2026, 11, 4, 10, 0, tzinfo=UTC)

    def test_con_offset(self):
        assert parse_feed_date("2026-11-04T10:00:00+01:00") == datetime(
            2026, 11, 4, 9, 0, tzinfo=UTC)

    def test_invalida_devuelve_default(self):
        centinela = datetime(2000, 1, 1, tzinfo=UTC)
        assert parse_feed_date("no-es-fecha", default=centinela) is centinela

    def test_invalida_sin_default_lanza(self):
        with pytest.raises(ValueError):
            parse_feed_date("no-es-fecha")


class TestFechasDeAdaptadores:
    def test_nvd_sin_zona_se_asume_utc(self):
        """NVD publica `published` sin `Z`; debe salir aware, no naive."""
        parsed = _parse_nvd_date("2026-11-11T22:17:10.820")
        assert parsed.tzinfo is not None
        assert parsed == datetime(2026, 11, 11, 22, 17, 10, 820000, tzinfo=UTC)

    def test_nvd_con_z_se_respeta(self):
        parsed = _parse_nvd_date("2026-11-11T22:17:10Z")
        assert parsed == datetime(2026, 11, 11, 22, 17, 10, tzinfo=UTC)

    def test_nvd_fecha_invalida_no_es_naive(self):
        assert _parse_nvd_date("no-es-fecha").tzinfo is not None

    def test_kev_solo_fecha_sale_aware(self):
        """KEV entrega `dateAdded` como fecha sin hora; debe salir aware."""
        entradas = KevAdapter().normalize([
            {"cveID": "CVE-2024-1111", "shortDescription": "x", "dateAdded": "2026-11-10"},
        ])
        assert entradas[0].published.tzinfo is not None


class TestCachePreservaZona:
    def test_round_trip_conserva_aware(self, tmp_path):
        cache = FeedCache(tmp_path / "c.json", ttl_minutes=15)
        cache.set("nvd", [FeedEntry(
            source_id="nvd:CVE-2024-1", source="nvd", title="t", description="d",
            url="u", published=datetime(2026, 11, 11, tzinfo=UTC))])
        recuperado = cache.get("nvd")
        assert recuperado is not None
        assert recuperado[0].published.tzinfo is not None

    def test_legacy_naive_se_completa_a_utc(self):
        """Un caché viejo con timestamp naive no debe reintroducir el TypeError."""
        aware = _aware_o_ahora("2026-11-10T00:00:00")
        assert aware.tzinfo is not None
        assert aware == datetime(2026, 11, 10, tzinfo=UTC)

    def test_aware_no_se_altera(self):
        aware = _aware_o_ahora("2026-11-10T00:00:00+00:00")
        assert aware == datetime(2026, 11, 10, tzinfo=UTC)


class TestNormalizadorConFechasMixtas:
    def test_mezcla_naive_y_aware_no_lanza(self):
        """Con la corrección, el normalizador nunca ve naive; con naive lanzaba.

        Se mezcla una entrada aware (NVD/EPSS) y el resultado del adaptador KEV
        ya corregido para comprobar que la comparación de ventana no revienta.
        """
        ahora = datetime.now(UTC)
        entradas = FeedNormalizer().normalize_all({
            "nvd": [FeedEntry(source_id="nvd:CVE-2024-1", source="nvd", title="t",
                              description="d", url="u", published=ahora, severity=7.0)],
            "kev": KevAdapter().normalize([
                {"cveID": "CVE-2024-2", "shortDescription": "x", "dateAdded": "2026-11-10"},
            ]),
        }, hours=24 * 365 * 10)
        assert {e.source_id for e in entradas} == {"nvd:CVE-2024-1", "kev:CVE-2024-2"}
        assert all(e.published.tzinfo is not None for e in entradas)
