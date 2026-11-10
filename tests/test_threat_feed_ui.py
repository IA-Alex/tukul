"""Integración de `threat_feed` en la UI (`ContextController`).

No se levanta ninguna ventana Tk: el controlador de contexto se instancia con
un host doble (un `MagicMock` con los métodos de contexto reales enlazados),
`build_threat_context` se mockea (nunca se sale a la red) y `after` se ejecuta
de forma síncrona. Se verifica que:

- el fetch solo ocurre si el usuario confirma (acción explícita, no automática);
- un fetch correcto entra como una instantánea de contexto y se autoriza;
- re-fetch reemplaza (upsert por `source_id`), no duplica;
- un `ThreatFeedError` se reporta y no añade contexto;
- el paquete resultante fluye por `_reference_packet` como cualquier contexto.

El pipeline vive ahora en `tukul_ui.contexto_dialogo`; los consumidores del
contexto (upsert, autorización) se llaman *en el host*, que es la ventana.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tukul_ui.app import (
    THREAT_FEED_HOURS,
    THREAT_FEED_SOURCE_ID,
    ContextArticle,
    TukulApp,
)
from tukul_ui.contexto_dialogo import ContextController
from tukul_ui.worker_threads import WorkerThreads

_PACKET = "Contexto de amenazas (CVE)\n\nCVE-2026-10001\n  ...\n"
_FILES = ["nvd:recent-24h", "epss", "cisa-kev"]


def _host() -> MagicMock:
    """Host doble: `after` ejecuta de inmediato; el contexto es real."""
    host = MagicMock()
    host.after = lambda _delay, fn: fn()
    host.closing = False
    host.context_articles = []
    # Upsert real sobre la lista real: es el comportamiento que se quiere fijar.
    host._upsert_context_article = TukulApp._upsert_context_article.__get__(host)
    host._update_references_button = MagicMock()
    host._authorize_context_articles = MagicMock()
    return host


def _controller(host: MagicMock) -> ContextController:
    return ContextController(
        host,
        threat_feed_hours=THREAT_FEED_HOURS,
        threat_feed_source_id=THREAT_FEED_SOURCE_ID,
        max_indexed_file_bytes=50_000,
    )


def _run_thread_synchronously() -> None:
    """Ejecuta el `work()` que `fetch_threat_feed` dejó en un hilo daemon."""
    vivos = WorkerThreads.vivos()
    assert vivos, "no se lanzó ningún hilo de fetch"
    vivos[-1]._target()  # type: ignore[attr-defined]
    WorkerThreads.esperar(5)


def test_no_hay_fetch_si_el_usuario_no_confirma():
    host = _host()
    dialog = MagicMock()
    with patch("tukul_ui.contexto_dialogo.messagebox.askyesno", return_value=False), \
         patch("tukul_ui.contexto_dialogo.build_threat_context") as build:
        _controller(host).fetch_threat_feed(dialog, on_done=MagicMock())
    build.assert_not_called()
    assert WorkerThreads.vivos() == []


def test_fetch_correcto_anade_contexto_y_lo_autoriza():
    host = _host()
    dialog = MagicMock()
    on_done = MagicMock()
    with patch("tukul_ui.contexto_dialogo.messagebox.askyesno", return_value=True), \
         patch("tukul_ui.contexto_dialogo.build_threat_context",
               return_value=(_PACKET, _FILES)) as build, \
         patch("tukul_ui.contexto_dialogo.threading.Thread") as thread_cls:
        thread_cls.side_effect = lambda target, daemon: MagicMock(_target=target)
        _controller(host).fetch_threat_feed(dialog, on_done)
        _run_thread_synchronously()

    build.assert_called_once_with(hours=THREAT_FEED_HOURS)
    entradas = [a for a in host.context_articles if a.source_id == THREAT_FEED_SOURCE_ID]
    assert len(entradas) == 1
    article = entradas[0]
    assert isinstance(article, ContextArticle)
    assert article.content == _PACKET
    host._authorize_context_articles.assert_called_once()
    on_done.assert_called_once()


def test_threat_feed_error_se_reporta_y_no_anade_contexto():
    from tukul_core.threat_feed import ThreatFeedError

    host = _host()
    dialog = MagicMock()
    with patch("tukul_ui.contexto_dialogo.messagebox.askyesno", return_value=True), \
         patch("tukul_ui.contexto_dialogo.messagebox.showerror") as showerror, \
         patch("tukul_ui.contexto_dialogo.build_threat_context",
               side_effect=ThreatFeedError("Ninguna fuente respondió.")), \
         patch("tukul_ui.contexto_dialogo.threading.Thread") as thread_cls:
        thread_cls.side_effect = lambda target, daemon: MagicMock(_target=target)
        _controller(host).fetch_threat_feed(dialog, on_done=MagicMock())
        _run_thread_synchronously()

    showerror.assert_called_once()
    assert host.context_articles == []
    host._authorize_context_articles.assert_not_called()


def test_no_toca_tcl_si_la_ventana_se_esta_cerrando():
    host = _host()
    host.after = MagicMock()  # si se llamara, fallaría la aserción de abajo
    with patch("tukul_ui.contexto_dialogo.messagebox.askyesno", return_value=True), \
         patch("tukul_ui.contexto_dialogo.build_threat_context", return_value=(_PACKET, _FILES)), \
         patch("tukul_ui.contexto_dialogo.threading.Thread") as thread_cls:
        thread_cls.side_effect = lambda target, daemon: MagicMock(_target=target)
        _controller(host).fetch_threat_feed(MagicMock(), on_done=MagicMock())
        host.closing = True
        _run_thread_synchronously()
    host.after.assert_not_called()


def test_refetch_reemplaza_no_duplica_via_source_id():
    # upsert real sobre una lista real: dos fetches -> una entrada.
    host = _host()
    ctrl = _controller(host)

    for content in ("paquete v1", "paquete v2"):
        ctrl.on_threat_feed_ready(content, _FILES, on_done=MagicMock())

    entradas = [a for a in host.context_articles if a.source_id == THREAT_FEED_SOURCE_ID]
    assert len(entradas) == 1
    assert entradas[0].content == "paquete v2"


def test_el_paquete_de_amenazas_fluye_por_reference_packet():
    from tukul_core.models import LlmProfile

    host = _host()
    host.profile = LlmProfile(
        name="t", provider="openai_compatible", endpoint="https://x", model="m",
        max_context_chars=100_000,
    )
    _controller(host).on_threat_feed_ready(_PACKET, _FILES, on_done=MagicMock())

    # `_reference_packet` sigue viviendo en `TukulApp`: se enlaza sobre el host.
    host.approved_contexts = None
    packet, files = TukulApp._reference_packet(host)
    assert "CVE-2026-10001" in packet
    assert any("CVEs recientes" in f for f in files)
