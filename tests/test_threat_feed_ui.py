"""Integración de `threat_feed` en la UI (`TukulApp`).

No se levanta ninguna ventana Tk: los métodos de integración se invocan
enlazados a un `MagicMock` que hace de app, con `build_threat_context` mockeado
(nunca se sale a la red) y `after` ejecutado de forma síncrona. Se verifica que:

- el fetch solo ocurre si el usuario confirma (acción explícita, no automática);
- un fetch correcto entra como una instantánea de contexto y se autoriza;
- re-fetch reemplaza (upsert por `source_id`), no duplica;
- un `ThreatFeedError` se reporta y no añade contexto;
- el paquete resultante fluye por `_reference_packet` como cualquier contexto.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tukul_ui.app import (
    THREAT_FEED_HOURS,
    THREAT_FEED_SOURCE_ID,
    ContextArticle,
    TukulApp,
)

_PACKET = "Contexto de amenazas (CVE)\n\nCVE-2026-10001\n  ...\n"
_FILES = ["nvd:recent-24h", "epss", "cisa-kev"]


def _app() -> MagicMock:
    """App simulada: `after` ejecuta de inmediato, el resto son mocks."""
    app = MagicMock()
    app.after = lambda _delay, fn: fn()
    app.closing = False
    app._worker_threads = []
    app.context_articles = []
    # Los tres métodos reales que queremos ejercitar de verdad:
    app._fetch_threat_feed = TukulApp._fetch_threat_feed.__get__(app)
    app._on_threat_feed_ready = TukulApp._on_threat_feed_ready.__get__(app)
    app._on_threat_feed_error = TukulApp._on_threat_feed_error.__get__(app)
    return app


def _run_thread_synchronously(app: MagicMock) -> None:
    """Ejecuta el `work()` que `_fetch_threat_feed` dejó en un Thread daemon."""
    assert app._worker_threads, "no se lanzó ningún hilo de fetch"
    target = app._worker_threads[-1]._target  # type: ignore[union-attr]
    target()


def test_no_hay_fetch_si_el_usuario_no_confirma():
    app = _app()
    dialog = MagicMock()
    with patch("tukul_ui.app.messagebox.askyesno", return_value=False), \
         patch("tukul_ui.app.build_threat_context") as build:
        app._fetch_threat_feed(dialog, on_done=MagicMock())
    build.assert_not_called()
    assert app._worker_threads == []


def test_fetch_correcto_anade_contexto_y_lo_autoriza():
    app = _app()
    dialog = MagicMock()
    on_done = MagicMock()
    with patch("tukul_ui.app.messagebox.askyesno", return_value=True), \
         patch("tukul_ui.app.build_threat_context", return_value=(_PACKET, _FILES)) as build, \
         patch("tukul_ui.app.threading.Thread") as thread_cls:
        thread_cls.side_effect = lambda target, daemon: MagicMock(_target=target)
        app._fetch_threat_feed(dialog, on_done)
        _run_thread_synchronously(app)

    build.assert_called_once_with(hours=THREAT_FEED_HOURS)
    app._upsert_context_article.assert_called_once()
    (article,), _ = app._upsert_context_article.call_args
    assert isinstance(article, ContextArticle)
    assert article.source_id == THREAT_FEED_SOURCE_ID
    assert article.content == _PACKET
    app._authorize_context_articles.assert_called_once()
    on_done.assert_called_once()


def test_threat_feed_error_se_reporta_y_no_anade_contexto():
    from tukul_core.threat_feed import ThreatFeedError

    app = _app()
    dialog = MagicMock()
    with patch("tukul_ui.app.messagebox.askyesno", return_value=True), \
         patch("tukul_ui.app.messagebox.showerror") as showerror, \
         patch("tukul_ui.app.build_threat_context",
               side_effect=ThreatFeedError("Ninguna fuente respondió.")), \
         patch("tukul_ui.app.threading.Thread") as thread_cls:
        thread_cls.side_effect = lambda target, daemon: MagicMock(_target=target)
        app._fetch_threat_feed(dialog, on_done=MagicMock())
        _run_thread_synchronously(app)

    showerror.assert_called_once()
    app._upsert_context_article.assert_not_called()
    app._authorize_context_articles.assert_not_called()


def test_no_toca_tcl_si_la_ventana_se_esta_cerrando():
    app = _app()
    app.after = MagicMock()  # si se llamara, fallaría la aserción de abajo
    with patch("tukul_ui.app.messagebox.askyesno", return_value=True), \
         patch("tukul_ui.app.build_threat_context", return_value=(_PACKET, _FILES)), \
         patch("tukul_ui.app.threading.Thread") as thread_cls:
        thread_cls.side_effect = lambda target, daemon: MagicMock(_target=target)
        app._fetch_threat_feed(MagicMock(), on_done=MagicMock())
        app.closing = True
        _run_thread_synchronously(app)
    app.after.assert_not_called()


def test_refetch_reemplaza_no_duplica_via_source_id():
    # _upsert_context_article real sobre una lista real: dos fetches -> una entrada.
    app = _app()
    app._update_references_button = MagicMock()
    app._upsert_context_article = TukulApp._upsert_context_article.__get__(app)
    app._authorize_context_articles = MagicMock()

    for content in ("paquete v1", "paquete v2"):
        app._on_threat_feed_ready(content, _FILES, on_done=MagicMock())

    entradas = [a for a in app.context_articles if a.source_id == THREAT_FEED_SOURCE_ID]
    assert len(entradas) == 1
    assert entradas[0].content == "paquete v2"


def test_el_paquete_de_amenazas_fluye_por_reference_packet():
    from tukul_core.models import LlmProfile

    app = _app()
    app._update_references_button = MagicMock()
    app._authorize_context_articles = MagicMock()
    app._upsert_context_article = TukulApp._upsert_context_article.__get__(app)
    app.profile = LlmProfile(
        name="t", provider="openai_compatible", endpoint="https://x", model="m",
        max_context_chars=100_000,
    )
    app._on_threat_feed_ready(_PACKET, _FILES, on_done=MagicMock())

    packet, files = TukulApp._reference_packet(app)
    assert "CVE-2026-10001" in packet
    assert any("CVEs recientes" in f for f in files)
