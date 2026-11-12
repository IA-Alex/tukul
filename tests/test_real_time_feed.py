"""Tests para `tukul_core.real_time_feed` e `impact_analyzer`.

Cubre:
- Dataclasses de modelos (FeedEntry, FoggAnalysis, SourceConflict,
  ConsumerSuggestion)
- FeedCache (TTL, persistencia, desalojo)
- FeedNormalizer (deduplicación, filtrado, enriquecimiento)
- CorrelationEngine e IdeaGenerator (correlación determinista y reglas)
- Adaptadores: contrato de red
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tukul_core.models import (
    ConsumerSuggestion,
    FeedEntry,
    FeedSource,
    FoggAnalysis,
    SourceConflict,
)
from tukul_core.real_time_feed import FeedCache, FeedNormalizer, FeedOrchestrator
from tukul_core.real_time_feed import orchestrator as orchestrator_module
from tukul_core.real_time_feed.adapters.arxiv import (
    ARXIV_API_URL,
    MAX_ATTEMPTS,
    NO_REDIRECT_OPENER,
    ArxivAdapter,
)
from tukul_core.real_time_feed.adapters.epss import (
    EPSS_ENDPOINT,
    EpssAdapter,
)
from tukul_core.real_time_feed.adapters.epss import (
    MAX_ATTEMPTS as MAX_ATTEMPTS_EPSS,
)
from tukul_core.real_time_feed.adapters.epss import (
    NO_REDIRECT_OPENER as NO_REDIRECT_OPENER_EPSS,
)

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

    def test_escribe_con_permisos_restrictivos_y_sin_temporal_fijo(self, tmp_path: Path) -> None:
        """La caché no deja un `.tmp` predecible ni un archivo legible por otros.

        Antes escribía con `with_suffix(".tmp")` y sin modo: un temporal de
        nombre fijo es sustituible por otro proceso y el archivo quedaba con el
        umask del proceso (típicamente 0644).
        """
        import stat as stat_module

        path = tmp_path / "cache.json"
        cache = FeedCache(path, ttl_minutes=15)
        now = datetime.now(UTC)
        cache.set("nvd", [FeedEntry(source_id="nvd:CVE-1", source="nvd",
                                    title="CVE-1", description="d", url="u",
                                    published=now)])
        assert path.exists()
        # 0600: el archivo no es legible por otros usuarios de la máquina.
        assert stat_module.S_IMODE(path.stat().st_mode) == 0o600
        # No queda ningún temporal hermano (el `.tmp` de nombre fijo).
        sobrantes = [p.name for p in tmp_path.iterdir() if p.name != "cache.json"]
        assert sobrantes == [], f"temporales sobrantes: {sobrantes}"
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


# ─── Tests de adaptadores: contrato de red ─────────────────────────────────

class TestArxivAdapterFetch:
    """El adaptador de arXiv debe poder CONSULTAR, no solo normalizar.

    El resto de la suite solo ejercitaba `normalize()` con datos sintéticos, así
    que la URL del endpoint nunca se comprobaba. Con `http://` arXiv responde
    301, y como `NO_REDIRECT_OPENER` rechaza toda redirección (a propósito, para
    no reenviar credenciales), el 301 llegaba como `HTTPError` no reintentable:
    el adaptador fallaba SIEMPRE. Estos tests fijan el contrato que faltaba.
    """

    def test_el_endpoint_usa_https(self):
        """https es obligatorio: con http:// el 301 de arXiv rompe el fetch."""
        assert ARXIV_API_URL.startswith("https://"), (
            "arXiv responde 301 hacia https y el opener no sigue redirecciones; "
            "con http:// el adaptador no puede funcionar nunca."
        )

    def test_fetch_pide_al_endpoint_correcto_y_devuelve_las_entradas(self):
        """`fetch()` consulta el endpoint y delega el parseo del Atom recibido."""
        atom = (
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            b"<entry><id>http://arxiv.org/abs/1</id>"
            b"<title>Paper uno</title><summary>resumen</summary>"
            b"<published>2026-01-01T00:00:00Z</published></entry></feed>"
        )
        urls_vistas: list[str] = []

        def _open(request, timeout=None):
            urls_vistas.append(request.full_url)
            # read(n) debe agotarse como un cuerpo real: los bytes y luego b"".
            cuerpo = iter([atom, b""])
            respuesta = MagicMock()
            respuesta.read.side_effect = lambda *_a: next(cuerpo)
            respuesta.headers = {}
            return respuesta

        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=_open):
            entradas = ArxivAdapter().fetch(24)

        # Dos categorías consultadas (cs.CR y cs.AI).
        assert len(entradas) == 2
        assert entradas[0]["category"] == "cs.CR"
        assert entradas[1]["category"] == "cs.AI"
        assert len(urls_vistas) == 2
        for url in urls_vistas:
            assert url.startswith(f"{ARXIV_API_URL}?")

    def test_un_301_se_reintenta_y_luego_se_propaga_como_error(self):
        """Una redirección termina en error legible en vez de colarse en silencio.

        `_fetch_category` reintenta todo `HTTPError` hasta `MAX_ATTEMPTS`, así
        que un 301 agota los intentos y se propaga como error con el código
        visible: nunca devuelve una lista vacía que oculte el fallo.
        """
        import urllib.error
        from email.message import Message

        error = urllib.error.HTTPError(
            ARXIV_API_URL, 301, "Moved Permanently", Message(), None
        )
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=error) as abrir:
            # El backoff real dormiría; aquí solo importa cuántas veces reintenta.
            with patch.object(ArxivAdapter, "_sleep", return_value=None):
                with pytest.raises(Exception, match="301"):
                    ArxivAdapter()._fetch_category("cs.CR", 24)

        assert abrir.call_count == MAX_ATTEMPTS, (
            "Los HTTPError se reintentan hasta agotar MAX_ATTEMPTS antes de fallar."
        )

    def test_metadatos_de_fuente(self):
        """`source_id`/`label` identifican la fuente ante el orquestador."""
        assert ArxivAdapter.source_id() == "arxiv"
        assert "arXiv" in ArxivAdapter.label()

    def test_un_error_de_red_se_reintenta_y_luego_se_propaga(self):
        """URLError (DNS caído, conexión rechazada) agota intentos y falla claro."""
        import urllib.error

        error = urllib.error.URLError("name resolution failed")
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=error) as abrir:
            with patch.object(ArxivAdapter, "_sleep", return_value=None):
                with pytest.raises(Exception, match="No se pudo conectar con arXiv"):
                    ArxivAdapter()._fetch_category("cs.CR", 24)
        assert abrir.call_count == MAX_ATTEMPTS

    def test_timeout_agota_intentos_con_mensaje_legible(self):
        """TimeoutError también entra en el bucle de reintento y no cuela vacío."""
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=TimeoutError("tardó")):
            with patch.object(ArxivAdapter, "_sleep", return_value=None):
                with pytest.raises(Exception, match="No se pudo conectar con arXiv"):
                    ArxivAdapter()._fetch_category("cs.CR", 24)

    def test_atom_malformado_devuelve_vacio_sin_lanzar(self):
        """Un cuerpo que no es XML válido no rompe el pipeline: degrada a []."""
        assert ArxivAdapter()._parse_atom(b"<feed><entry", "cs.CR") == []

    def test_un_dtd_se_rechaza_sin_expandir_entidades(self):
        """XXE / «billion laughs»: un DTD hace que el parseo se rechace.

        `xml.etree` expande entidades *durante* el parseo, así que un cuerpo
        pequeño puede agotar la memoria aunque se acote el número de bytes
        leídos (bandit B314/B405). El ayudante `xml_fromstring_seguro` rechaza
        cualquier documento con DTD, que es el único vector de esos ataques.
        """
        bomba = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
            b'<!ENTITY lol2 "&lol;&lol;&lol;">]>'
            b"<feed><entry>&lol2;</entry></feed>"
        )
        assert ArxivAdapter()._parse_atom(bomba, "cs.CR") == []

    def test_un_atom_valido_sin_dtd_sigue_parseandose(self):
        """El endurecimiento no afecta a las respuestas legítimas (sin DTD)."""
        atom = (
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            b"<entry><id>http://arxiv.org/abs/9</id><title>Paper</title>"
            b"<summary>r</summary>"
            b"<published>2026-01-01T00:00:00Z</published></entry></feed>"
        )
        entradas = ArxivAdapter()._parse_atom(atom, "cs.CR")
        assert len(entradas) == 1
        assert entradas[0]["title"] == "Paper"

    def test_entry_sin_titulo_o_id_se_descarta(self):
        """Entradas sin título o sin id no producen FeedEntry parcial."""
        atom = (
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            b"<entry><title>Sin id</title></entry>"
            b"<entry><id>http://arxiv.org/abs/2</id></entry>"
            b"</feed>"
        )
        assert ArxivAdapter()._parse_atom(atom, "cs.CR") == []

    def test_respuesta_sobredimensionada_se_rechaza(self):
        """El techo de bytes corta una respuesta que intenta agotar memoria."""
        from tukul_core.real_time_feed.adapters.arxiv import MAX_RESPONSE_BYTES

        respuesta = MagicMock()
        respuesta.read.side_effect = [b"x" * (MAX_RESPONSE_BYTES + 1)]
        with pytest.raises(RuntimeError, match="supera límite"):
            ArxivAdapter()._read_bounded(respuesta)

    def test_normalize_convierte_y_tolera_fecha_invalida(self):
        """`normalize` produce FeedEntry y cae a `now` si la fecha es inválida."""
        crudo = [{
            "id": "http://arxiv.org/abs/1", "title": "Paper", "summary": "s",
            "published": "no-es-una-fecha", "category": "cs.AI",
        }]
        entradas = ArxivAdapter().normalize(crudo)
        assert len(entradas) == 1
        assert entradas[0].source == "arxiv"
        assert "inteligencia_artificial" in entradas[0].topics

    def test_normalize_publica_la_url_en_https(self):
        """El `atom:id` de arXiv es `http://`; la entrada debe llevar HTTPS.

        El enlace viaja al contexto y al caché; publicarlo en `http://` degrada
        la conexión y contradice al resto de fuentes (y a `SearchResult`, que
        exige https). El `source_id` se mantiene intacto para no romper la
        correlación por id.
        """
        crudo = [{
            "id": "http://arxiv.org/abs/2601.00001", "title": "Paper",
            "summary": "s", "published": "2026-01-01T00:00:00Z", "category": "cs.CR",
        }]
        entrada = ArxivAdapter().normalize(crudo)[0]
        assert entrada.url == "https://arxiv.org/abs/2601.00001"
        assert entrada.source_id == "arxiv:http://arxiv.org/abs/2601.00001"

    def test_arxiv_url_https_tolera_formas_no_url(self):
        """Id vacío o no reconocible se devuelve tal cual: no se inventa enlace."""
        from tukul_core.real_time_feed.adapters.arxiv import _arxiv_url_https

        assert _arxiv_url_https("") == ""
        assert _arxiv_url_https("raro-sin-esquema") == "raro-sin-esquema"
        assert _arxiv_url_https("https://arxiv.org/abs/9") == "https://arxiv.org/abs/9"
        assert _arxiv_url_https("arxiv.org/abs/2") == "https://arxiv.org/abs/2"

    def test_sleep_aplica_backoff_con_jitter_acotado(self):
        """El backoff nunca supera `BACKOFF_MAX * 1.25`, aun con jitter máximo."""
        from tukul_core.real_time_feed.adapters.arxiv import BACKOFF_MAX

        capturado: list[float] = []
        with patch("tukul_core.real_time_feed.adapters.arxiv.time.sleep",
                   side_effect=lambda s: capturado.append(s)), \
             patch("tukul_core.real_time_feed.adapters.arxiv.random.random",
                   return_value=1.0):
            ArxivAdapter()._sleep(1)
        assert capturado and capturado[0] <= BACKOFF_MAX * 1.25


# ─── Tests de FeedOrchestrator ─────────────────────────────────────────────
# El orquestador corre hilos, agrega fuentes y decide la degradación. Un bug
# real (arXiv con `http://`) pasó precisamente por no ejercitar `fetch()`.
# Aquí se sustituye `REGISTRY` por adaptadores de doble, así que no hay red.

class _AdaptadorDoble:
    """Adaptador de prueba que devuelve entradas prefabricadas o falla."""

    def __init__(self, sid: str, entradas=None, error: Exception | None = None):
        self._sid = sid
        self._entradas = entradas or []
        self._error = error

    def fetch(self, hours: int):
        if self._error is not None:
            raise self._error
        return self._entradas

    def normalize(self, raw):
        return list(raw)


def _entrada(sid: str, source: str, severity: float | None = None,
             published: datetime | None = None) -> FeedEntry:
    return FeedEntry(
        source_id=sid, source=source, title=sid, description="d", url="u",
        published=published or datetime.now(UTC), severity=severity,
    )


@pytest.fixture()
def _registro(monkeypatch):
    """Aísla cada test: REGISTRY propio y sin adaptadores reales.

    `orchestrator` importa `REGISTRY` por nombre, así que hay que parchear
    tanto el módulo de adaptadores como el del orquestador.
    """
    registro: dict = {}
    monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
    return registro


class TestFeedOrchestrator:
    def test_sin_fuentes_devuelve_vacio_sin_consultar(self, tmp_path: Path, _registro):
        """`sources=[]` no dispara ninguna consulta ni error.

        Se registra un adaptador que fallaría si se invocara: así el test
        distingue «no consultó» de «consultó y no devolvió nada».
        """
        def _no_debe_llamarse():
            raise AssertionError("sources=[] no debe instanciar adaptadores")

        _registro["centinela"] = _no_debe_llamarse
        o = FeedOrchestrator(tmp_path / "c.json")
        assert o.fetch_all(sources=[]) == []

    def test_fuente_inexistente_no_rompe_el_resto(self, tmp_path, monkeypatch):
        """Un ID desconocido se registra como error sin tumbar las demás."""
        registro = {
            "buena": lambda: _AdaptadorDoble("buena", [_entrada("buena:1", "buena")]),
        }
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        resultado = o.fetch_all(sources=["buena", "fantasma"])
        assert [e.source_id for e in resultado] == ["buena:1"]

    def test_todas_las_fuentes_fallan_lanza_error_con_detalle(self, tmp_path, monkeypatch):
        """Si todas fallan, el error incluye el motivo de cada una."""
        registro = {
            "a": lambda: _AdaptadorDoble("a", error=RuntimeError("timeout a")),
            "b": lambda: _AdaptadorDoble("b", error=RuntimeError("404 b")),
        }
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        with pytest.raises(RuntimeError) as excinfo:
            o.fetch_all(sources=["a", "b"])
        mensaje = str(excinfo.value)
        assert "timeout a" in mensaje and "404 b" in mensaje

    def test_una_fuente_rota_no_impide_la_degradacion_parcial(self, tmp_path, monkeypatch):
        """Degradación granular: la que funciona entrega sus entradas."""
        registro = {
            "ok": lambda: _AdaptadorDoble("ok", [_entrada("ok:1", "ok", severity=5.0)]),
            "rota": lambda: _AdaptadorDoble("rota", error=RuntimeError("boom")),
        }
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        resultado = o.fetch_all(sources=["ok", "rota"])
        assert len(resultado) == 1 and resultado[0].source_id == "ok:1"

    def test_usa_el_cache_y_no_reconsulta(self, tmp_path, monkeypatch):
        """Con caché vigente no se vuelve a llamar al adaptador."""
        llamadas = {"n": 0}

        class _Cuenta(_AdaptadorDoble):
            def fetch(self, hours):
                llamadas["n"] += 1
                return super().fetch(hours)

        registro = {
            "src": lambda: _Cuenta("src", [_entrada("src:1", "src")]),
        }
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        o.fetch_all(sources=["src"])
        o.fetch_all(sources=["src"])
        assert llamadas["n"] == 1, "La segunda llamada debe servirse del caché."

    def test_use_cache_false_fuerza_reconsulta(self, tmp_path, monkeypatch):
        """`use_cache=False` ignora el caché y vuelve a consultar."""
        llamadas = {"n": 0}

        class _Cuenta(_AdaptadorDoble):
            def fetch(self, hours):
                llamadas["n"] += 1
                return super().fetch(hours)

        registro = {"src": lambda: _Cuenta("src", [_entrada("src:1", "src")])}
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        o.fetch_all(sources=["src"])
        o.fetch_all(sources=["src"], use_cache=False)
        assert llamadas["n"] == 2

    def test_available_sources_refleja_el_registro(self, tmp_path, monkeypatch):
        """La lista para la UI sale del registro y expone id/label."""
        class _ConEtiqueta:
            @classmethod
            def source_id(cls):
                return "x"

            @classmethod
            def label(cls):
                return "Fuente X"

        monkeypatch.setattr(orchestrator_module, "REGISTRY", {"x": _ConEtiqueta})
        o = FeedOrchestrator(tmp_path / "c.json")
        assert o.available_sources() == [{"id": "x", "label": "Fuente X"}]

    def test_invalidate_cache_por_fuente_y_total(self, tmp_path, monkeypatch):
        """Invalidar una fuente o todo el caché no debe lanzar."""
        registro = {"x": lambda: _AdaptadorDoble("x", [_entrada("x:1", "x")])}
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        o.fetch_all(sources=["x"])
        o.invalidate_cache("x")
        o.invalidate_cache()  # total

    def test_epss_se_reconsulta_con_los_cve_de_nvd(self, tmp_path, monkeypatch):
        """El orquestador pide EPSS acotado a los CVE de NVD, no una muestra.

        Sin esto, EPSS `fetch(24)` sin `cve_ids` devuelve 100 filas arbitrarias
        del día que casi nunca cruzan con NVD: el enriquecimiento quedaba en
        no-op silencioso.
        """
        llamadas: list[list[str] | None] = []

        class _EpssDoble(_AdaptadorDoble):
            def fetch(self, hours, cve_ids=None):
                llamadas.append(cve_ids)
                if cve_ids:
                    # severity=9.8 → epss_score 0.98 (> 0.9 → alta probabilidad).
                    return [_entrada(f"epss:{cve}", "epss", severity=9.8)
                            for cve in cve_ids]
                return [_entrada("epss:CVE-0000-9999", "epss")]

        registro = {
            "nvd": lambda: _AdaptadorDoble("nvd", [
                _entrada("nvd:CVE-2026-0001", "nvd", severity=7.5),
                _entrada("nvd:CVE-2026-0002", "nvd", severity=6.0),
            ]),
            "epss": lambda: _EpssDoble("epss"),
        }
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        resultado = o.fetch_all(sources=["nvd", "epss"])

        # La última llamada a EPSS lleva los CVE de NVD, no None.
        assert llamadas[-1] is not None
        assert set(llamadas[-1]) == {"CVE-2026-0001", "CVE-2026-0002"}
        # Y el enriquecimiento aplicó el tag EPSS al CVE correspondiente.
        nvd_1 = next(e for e in resultado if e.source_id == "nvd:CVE-2026-0001")
        assert "alta_probabilidad_explotacion" in nvd_1.tags

    def test_epss_se_trocea_en_lotes_de_cien(self, tmp_path, monkeypatch):
        """Con muchos CVE, EPSS se pide en lotes de 100 (URLs no frágiles).

        Una query string con cientos de `cve=` es frágil; `threat_feed` ya
        trocea y el orquestador debe hacer lo mismo. Un lote caído no debe
        tumbar los demás (degradación granular).
        """
        lotes: list[list[str]] = []

        class _EpssDoble(_AdaptadorDoble):
            def fetch(self, hours, cve_ids=None):
                if cve_ids:
                    lotes.append(list(cve_ids))
                    if len(lotes) == 2:  # el 2.º lote falla
                        raise RuntimeError("lote caído")
                    return [_entrada(f"epss:{cve}", "epss", severity=9.8)
                            for cve in cve_ids]
                return []

        total_cve = orchestrator_module.EPSS_BATCH_SIZE * 2 + 5
        nvd = [
            _entrada(f"nvd:CVE-2026-{i:04d}", "nvd", severity=7.0)
            for i in range(total_cve)
        ]
        registro = {
            "nvd": lambda: _AdaptadorDoble("nvd", list(nvd)),
            "epss": lambda: _EpssDoble("epss"),
        }
        monkeypatch.setattr(orchestrator_module, "REGISTRY", registro)
        o = FeedOrchestrator(tmp_path / "c.json")
        resultado = o.fetch_all(sources=["nvd", "epss"])

        # Tres lotes: 100 + 100 + 5.
        assert [len(lote) for lote in lotes] == [100, 100, 5]
        # El lote 2 falló, pero los otros dos se mantienen.
        assert len([e for e in resultado if e.source == "epss"]) == 105


# ─── Tests de EpssAdapter: contrato de red y normalización ─────────────────
# EPSS enriquece NVD con la probabilidad de explotación. Sus rutas de error
# (429 con Retry-After, límite de bytes, score no numérico) son las que más
# importan: un score mal parseado se colaría como 0.0 silencioso.

class TestEpssAdapter:
    def test_metadatos_de_fuente(self):
        assert EpssAdapter.source_id() == "epss"
        assert "EPSS" in EpssAdapter.label()

    def test_429_se_reintenta_hasta_agotar(self):
        """429 es reintentable: agota MAX_ATTEMPTS y luego propaga error."""
        import urllib.error
        from email.message import Message

        error = urllib.error.HTTPError(
            EPSS_ENDPOINT, 429, "Too Many Requests", Message(), None
        )
        with patch.object(NO_REDIRECT_OPENER_EPSS, "open", side_effect=error) as abrir:
            with patch.object(EpssAdapter, "_sleep", return_value=None):
                with pytest.raises(RuntimeError, match="429"):
                    EpssAdapter().fetch(24)
        assert abrir.call_count == MAX_ATTEMPTS_EPSS

    def test_error_no_reintentable_falla_de_inmediato(self):
        """Un 404 no se reintenta: es un error de contrato, no de carga."""
        import urllib.error
        from email.message import Message

        error = urllib.error.HTTPError(
            EPSS_ENDPOINT, 404, "Not Found", Message(), None
        )
        with patch.object(NO_REDIRECT_OPENER_EPSS, "open", side_effect=error) as abrir:
            with pytest.raises(RuntimeError, match="404"):
                EpssAdapter().fetch(24)
        assert abrir.call_count == 1, "404 no es reintentable."

    def test_url_con_cve_ids_filtra_por_cve(self):
        """Con `cve_ids` la URL lleva los parámetros cve y no la fecha."""
        respuesta = MagicMock()
        respuesta.read.side_effect = [b'{"data": []}', b""]
        urls: list[str] = []

        def _open(request, timeout=None):
            urls.append(request.full_url)
            return respuesta

        with patch.object(NO_REDIRECT_OPENER_EPSS, "open", side_effect=_open):
            EpssAdapter().fetch(24, cve_ids=["CVE-2026-0001"])

        assert "cve=CVE-2026-0001" in urls[0]
        assert "date=" not in urls[0]

    def test_respuesta_sobredimensionada_se_rechaza(self):
        from tukul_core.real_time_feed.adapters.epss import MAX_RESPONSE_BYTES

        respuesta = MagicMock()
        respuesta.read.side_effect = [b"x" * (MAX_RESPONSE_BYTES + 1)]
        with pytest.raises(RuntimeError, match="supera el límite"):
            EpssAdapter()._read_bounded(respuesta)

    def test_normalize_omite_cve_vacio_y_tolera_score_invalido(self):
        """Sin CVE se descarta; un score no numérico cae a 0.0 sin romper."""
        entradas = EpssAdapter().normalize([
            {"epss": "0.5"},                       # sin cve → descartado
            {"cve": "CVE-2026-0002", "epss": "no-es-numero"},  # score inválido
            {"cve": "CVE-2026-0003", "epss": "0.95"},          # alta probabilidad
        ])
        assert [e.source_id for e in entradas] == [
            "epss:CVE-2026-0002", "epss:CVE-2026-0003",
        ]
        assert entradas[0].severity == 0.0
        assert "alta_probabilidad_explotacion" in entradas[1].tags

    def test_sleep_respeta_retry_after_y_lo_acota(self):
        """`Retry-After` se respeta pero nunca por encima de BACKOFF_MAX."""
        import urllib.error
        from email.message import Message

        from tukul_core.real_time_feed.adapters.epss import BACKOFF_MAX

        error = urllib.error.HTTPError(
            EPSS_ENDPOINT, 429, "slow", {"Retry-After": "999"}, None
        )
        capturado: list[float] = []
        with patch("tukul_core.real_time_feed.adapters.epss.time.sleep",
                   side_effect=lambda s: capturado.append(s)), \
             patch("tukul_core.real_time_feed.adapters.epss.random.random",
                   return_value=1.0):
            EpssAdapter()._sleep(error, 1)
        assert capturado and capturado[0] <= BACKOFF_MAX * 1.25
