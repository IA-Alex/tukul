"""Tests de `articulador_core.threat_feed`.

Toda la red se mockea sobre `http_safety.NO_REDIRECT_OPENER.open` (mismo enfoque
que los tests de `llm`: se sustituye el punto de apertura de la conexión, nunca
se sale a la red, y el opener compartido garantiza que un 3xx no se sigue). Se
cubren: éxito con las 3 fuentes, degradación con 1 y con 2 fuentes caídas, las 3
caídas (fallo claro), degradación por lote en EPSS, techo de tamaño excedido,
timeout, status retryable que sí reintenta, status no retryable que falla
directo, y el determinismo del packet.
"""
from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from articulador_core import threat_feed as tf
from articulador_core.threat_feed import (
    EpssError,
    KevError,
    NvdError,
    ResponseTooLargeError,
    ThreatFeedEntry,
    ThreatFeedError,
    build_threat_context,
    fetch_epss,
    fetch_kev,
    fetch_nvd_recent,
)


class _Response:
    """Doble mínimo de la respuesta de urlopen: context manager con read() y headers."""

    def __init__(self, body: bytes, content_length: str | None = None):
        self._buffer = io.BytesIO(body)
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amt: int = -1) -> bytes:
        return self._buffer.read(amt)


def _json_response(payload: object, content_length: str | None = None) -> _Response:
    return _Response(json.dumps(payload).encode("utf-8"), content_length)


# --- Payloads de referencia ---------------------------------------------
NVD_PAYLOAD = {
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2026-20002",
                "published": "2026-09-10T02:00:00.000",
                "descriptions": [{"lang": "en", "value": "Segundo CVE de prueba."}],
                "references": [{"url": "https://example.com/b"}],
                "metrics": {},
            }
        },
        {
            "cve": {
                "id": "CVE-2026-10001",
                "published": "2026-09-09T14:22:00.000",
                "descriptions": [
                    {"lang": "es", "value": "ignorado"},
                    {"lang": "en", "value": "Primer CVE de prueba."},
                ],
                "references": [
                    {"url": "https://example.com/a1"},
                    {"url": "https://example.com/a2"},
                ],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 9.8}}],
                },
            }
        },
    ]
}
EPSS_PAYLOAD = {
    "data": [
        {"cve": "CVE-2026-10001", "epss": "0.73200"},
        {"cve": "CVE-2026-20002", "epss": "0.01000"},
    ]
}
KEV_PAYLOAD = {"vulnerabilities": [{"cveID": "CVE-2026-10001"}]}


def _router(**by_host):
    """Devuelve un side_effect para urlopen que despacha por host de la URL."""

    def _urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        for host, factory in by_host.items():
            if host in url:
                result = factory() if callable(factory) else factory
                if isinstance(result, BaseException):
                    raise result
                return result
        raise AssertionError(f"URL no esperada en el test: {url}")

    return _urlopen


# --- ThreatFeedEntry ---------------------------------------------------
def test_entry_valida_campos():
    e = ThreatFeedEntry("CVE-2026-10001", "x", 9.8, 0.5, True, "2026-09-09", ("https://a",))
    assert e.cve_id == "CVE-2026-10001"
    with pytest.raises(ValueError):
        ThreatFeedEntry("no-cve", "x", None, None, False, "2026", ())
    with pytest.raises(ValueError):
        ThreatFeedEntry("CVE-2026-10001", "x", 11.0, None, False, "2026", ())
    with pytest.raises(ValueError):
        ThreatFeedEntry("CVE-2026-10001", "x", None, 1.5, False, "2026", ())
    with pytest.raises(ValueError):
        ThreatFeedEntry("CVE-2026-10001", "x", None, None, False, "  ", ())


# --- Éxito con las 3 fuentes ---------------------------------------------
def test_build_con_las_tres_fuentes():
    urlopen = _router(
        **{
            "services.nvd.nist.gov": lambda: _json_response(NVD_PAYLOAD),
            "api.first.org": lambda: _json_response(EPSS_PAYLOAD),
            "cisa.gov": lambda: _json_response(KEV_PAYLOAD),
        }
    )
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        packet, files = build_threat_context(hours=24)

    assert files == ["nvd:recent-24h", "epss", "cisa-kev"]
    # Orden determinista por CVE ID: el 10001 aparece antes que el 20002.
    assert packet.index("CVE-2026-10001") < packet.index("CVE-2026-20002")
    assert "9.8 (crítico)" in packet
    assert "0.732 (probabilidad de explotación a 30 días)" in packet
    assert "En catálogo CISA KEV: sí" in packet
    assert "Fuentes NO disponibles" not in packet
    assert "Resumen: 2 CVE en la ventana. 1 en KEV. EPSS disponible para 2." in packet


def test_packet_es_determinista_con_el_mismo_input():
    urlopen = _router(
        **{
            "services.nvd.nist.gov": lambda: _json_response(NVD_PAYLOAD),
            "api.first.org": lambda: _json_response(EPSS_PAYLOAD),
            "cisa.gov": lambda: _json_response(KEV_PAYLOAD),
        }
    )
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        first, files1 = build_threat_context(hours=24)
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        second, files2 = build_threat_context(hours=24)
    assert first == second
    assert files1 == files2


# --- Degradación: 1 fuente caída ---------------------------------------
def test_degrada_con_epss_caida():
    urlopen = _router(
        **{
            "services.nvd.nist.gov": lambda: _json_response(NVD_PAYLOAD),
            "api.first.org": lambda: urllib.error.URLError("epss down"),
            "cisa.gov": lambda: _json_response(KEV_PAYLOAD),
        }
    )
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        packet, files = build_threat_context(hours=24)

    assert files == ["nvd:recent-24h", "cisa-kev"]
    assert "Fuentes NO disponibles (contexto degradado): EPSS (FIRST.org)" in packet
    assert "EPSS: fuente no disponible" in packet
    assert "En catálogo CISA KEV: sí" in packet


# --- Degradación: 2 fuentes caídas -----------------------------------
def test_degrada_con_epss_y_kev_caidas():
    urlopen = _router(
        **{
            "services.nvd.nist.gov": lambda: _json_response(NVD_PAYLOAD),
            "api.first.org": lambda: urllib.error.URLError("epss down"),
            "cisa.gov": lambda: urllib.error.URLError("kev down"),
        }
    )
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        packet, files = build_threat_context(hours=24)

    assert files == ["nvd:recent-24h"]
    assert "EPSS (FIRST.org)" in packet
    assert "CISA KEV" in packet
    assert "EPSS: fuente no disponible" in packet
    assert "En catálogo CISA KEV: fuente no disponible" in packet


# --- Las 3 caídas: fallo claro, no silencioso -----------------------
def test_las_tres_caidas_lanza_error():
    urlopen = _router(
        **{
            "services.nvd.nist.gov": lambda: urllib.error.URLError("nvd down"),
            "api.first.org": lambda: urllib.error.URLError("epss down"),
            "cisa.gov": lambda: urllib.error.URLError("kev down"),
        }
    )
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        with pytest.raises(ThreatFeedError) as ctx:
            build_threat_context(hours=24)
    assert "Ninguna fuente" in str(ctx.value)


# --- Techo de tamaño de respuesta ----------------------------------
def test_techo_de_tamano_excedido_declarado():
    huge = _json_response(KEV_PAYLOAD, content_length=str(tf.MAX_RESPONSE_BYTES + 1))
    urlopen = _router(**{"cisa.gov": lambda: huge})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        with pytest.raises(ResponseTooLargeError):
            fetch_kev()


def test_techo_de_tamano_excedido_al_leer():
    body = b"x" * (tf.MAX_RESPONSE_BYTES + 10)
    urlopen = _router(**{"cisa.gov": lambda: _Response(body)})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        with pytest.raises(ResponseTooLargeError):
            fetch_kev()


# --- Timeout ------------------------------------------------------
def test_timeout_se_envuelve_en_error_tipado():
    urlopen = _router(**{"services.nvd.nist.gov": lambda: TimeoutError("timed out")})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep") as dormir:
        with pytest.raises(NvdError):
            fetch_nvd_recent(hours=24)
    # Se reintentó: MAX_HTTP_ATTEMPTS - 1 esperas.
    assert dormir.call_count == tf.MAX_HTTP_ATTEMPTS - 1


# --- Status retryable que sí reintenta -----------------------------
def test_status_retryable_reintenta_y_luego_responde():
    intentos = []

    def factory():
        intentos.append(1)
        if len(intentos) == 1:
            return urllib.error.HTTPError(
                "https://api.first.org", 503, "unavailable", {}, io.BytesIO(b"{}")
            )
        return _json_response(EPSS_PAYLOAD)

    urlopen = _router(**{"api.first.org": factory})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep") as dormir:
        scores = fetch_epss(["CVE-2026-10001", "CVE-2026-20002"])
    assert len(intentos) == 2
    assert scores["CVE-2026-10001"] == pytest.approx(0.732)
    dormir.assert_called_once()


def test_retry_after_se_acota_al_maximo():
    def factory():
        return urllib.error.HTTPError(
            "https://api.first.org", 429, "slow", {"Retry-After": "999"}, io.BytesIO(b"{}")
        )

    urlopen = _router(**{"api.first.org": factory})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep") as dormir:
        with pytest.raises(EpssError):
            fetch_epss(["CVE-2026-10001"])
    assert dormir.call_args_list[0][0][0] <= tf.BACKOFF_MAX_SECONDS


# --- Status no retryable que falla directo ------------------------
def test_status_no_retryable_falla_sin_reintentar():
    def factory():
        return urllib.error.HTTPError(
            "https://services.nvd.nist.gov", 403, "forbidden", {}, io.BytesIO(b"{}")
        )

    urlopen = _router(**{"services.nvd.nist.gov": factory})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep") as dormir:
        with pytest.raises(NvdError) as ctx:
            fetch_nvd_recent(hours=24)
    assert "403" in str(ctx.value)
    dormir.assert_not_called()


# --- urllib.error no se propaga crudo -----------------------------
def test_no_propaga_urllib_error_crudo():
    urlopen = _router(
        **{
            "services.nvd.nist.gov": lambda: _json_response(NVD_PAYLOAD),
            "api.first.org": lambda: _json_response(EPSS_PAYLOAD),
            "cisa.gov": lambda: urllib.error.HTTPError(
                "https://www.cisa.gov", 404, "nf", {}, io.BytesIO(b"{}")
            ),
        }
    )
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        # KEV 404 no retryable -> KevError, capturado por build -> degradación.
        _packet, files = build_threat_context(hours=24)
    assert "cisa-kev" not in files
    assert isinstance(KevError("x"), ThreatFeedError)


def test_fetch_nvd_rechaza_hours_no_positivo():
    with pytest.raises(NvdError):
        fetch_nvd_recent(hours=0)


# --- Jitter en el backoff exponencial ----------------------------
def test_backoff_lleva_jitter_y_se_acota():
    # Sin Retry-After: el delay es exponencial con jitter, nunca supera el techo
    # (con el 25 % de margen) y no es exactamente el valor determinista.
    deterministic = tf.BACKOFF_BASE_SECONDS  # attempt=1 -> base * 2^0
    delays = {tf._retry_delay(1, None) for _ in range(50)}
    assert len(delays) > 1  # hay jitter: no todos iguales
    assert all(0 < d <= tf.BACKOFF_MAX_SECONDS * 1.25 for d in delays)
    assert deterministic not in delays or len(delays) > 1


# --- EPSS degrada por lote --------------------------------------
def test_epss_degrada_lote_fallido_y_conserva_los_demas():
    ids = [f"CVE-2026-{10000 + i:05d}" for i in range(tf.EPSS_BATCH_SIZE + 5)]
    llamadas = []

    def factory():
        llamadas.append(1)
        if len(llamadas) == 1:  # primer lote OK
            return _json_response({"data": [{"cve": ids[0], "epss": "0.50000"}]})
        return urllib.error.URLError("segundo lote caído")  # segundo lote falla

    urlopen = _router(**{"api.first.org": factory})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        scores = fetch_epss(ids)
    assert scores == {ids[0]: pytest.approx(0.5)}  # se conserva lo del lote bueno


def test_epss_lanza_si_fallan_todos_los_lotes():
    urlopen = _router(**{"api.first.org": lambda: urllib.error.URLError("epss down")})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        with pytest.raises(EpssError):
            fetch_epss(["CVE-2026-10001"])


# --- Redirect no se sigue --------------------------------------
def test_un_redirect_de_la_fuente_no_se_sigue():
    # El opener compartido convierte el 3xx en HTTPError; fetch_kev lo envuelve
    # en KevError sin haber procesado ningún cuerpo redirigido.
    def factory():
        return urllib.error.HTTPError(
            "https://www.cisa.gov", 302, "Found",
            {"Location": "https://otro-origen.example/x"}, io.BytesIO(b""),
        )

    urlopen = _router(**{"cisa.gov": factory})
    with patch("articulador_core.http_safety.NO_REDIRECT_OPENER.open", side_effect=urlopen), patch("time.sleep"):
        with pytest.raises(KevError):
            fetch_kev()
