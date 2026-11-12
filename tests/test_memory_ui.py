from pathlib import Path
from unittest.mock import MagicMock, patch

from tukul_ui.contexto_dialogo import ContextController


def _controller(tmp_path: Path) -> tuple[ContextController, MagicMock]:
    root = tmp_path / "Articulos"
    root.mkdir()
    (root / "tema.md").write_text("# Sicofancia\nCriterio humano", encoding="utf-8")
    host = MagicMock()
    host.closing = False
    host.after = lambda _delay, callback: callback()
    host.status.set = MagicMock()
    controller = ContextController(
        host,
        threat_feed_hours=24,
        threat_feed_source_id="threat-feed:test",
        max_indexed_file_bytes=50_000,
        memory_root=root,
        memory_database_path=tmp_path / "memory.sqlite3",
    )
    return controller, host


def test_search_memory_indexes_and_returns_results_without_touching_context(tmp_path):
    controller, host = _controller(tmp_path)
    shown = MagicMock()
    controller._show_memory_results = shown

    with patch("tukul_ui.contexto_dialogo.simpledialog.askstring", return_value="criterio"), \
         patch("tukul_ui.contexto_dialogo.WorkerThreads.start",
               side_effect=lambda target: target()):
        controller.search_memory(MagicMock())

    shown.assert_called_once()
    results = shown.call_args.args[2]
    assert results[0].relative_path == "tema.md"
    host.status.set.assert_any_call("Buscando en la memoria local…")


def test_search_memory_cancelled_query_does_not_start_worker(tmp_path):
    controller, _host = _controller(tmp_path)

    with patch("tukul_ui.contexto_dialogo.simpledialog.askstring", return_value=""), \
         patch("tukul_ui.contexto_dialogo.WorkerThreads.start") as start:
        controller.search_memory(MagicMock())

    start.assert_not_called()
