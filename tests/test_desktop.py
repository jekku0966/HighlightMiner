from __future__ import annotations

import sys
import threading
import types

import pytest

import highlightminer.desktop as desktop
from highlightminer.desktop import (
    active_work_shutdown_block_reason,
    resolve_ui_mode,
    wait_for_server,
)


def test_windows_defaults_to_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIGHLIGHTMINER_UI_MODE", raising=False)
    assert resolve_ui_mode(platform_name="nt") == "desktop"


def test_non_windows_defaults_to_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIGHLIGHTMINER_UI_MODE", raising=False)
    assert resolve_ui_mode(platform_name="posix") == "browser"


def test_browser_flag_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGHLIGHTMINER_UI_MODE", "desktop")
    assert resolve_ui_mode(browser_requested=True, platform_name="nt") == "browser"


def test_server_mode_can_be_forced_for_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGHLIGHTMINER_UI_MODE", "server")
    assert resolve_ui_mode(platform_name="nt") == "server"


def test_invalid_ui_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGHLIGHTMINER_UI_MODE", "abomination")
    with pytest.raises(ValueError, match="Invalid HIGHLIGHTMINER_UI_MODE"):
        resolve_ui_mode(platform_name="nt")


def test_wait_for_server_fails_fast_if_child_exits() -> None:
    class DeadProcess:
        @staticmethod
        def poll() -> int:
            return 7

    with pytest.raises(RuntimeError, match="exit code 7"):
        wait_for_server(DeadProcess(), timeout=1.0)


def test_shutdown_block_reason_only_reports_work_that_cannot_be_safely_stopped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db = tmp_path / "highlightminer.db"
    monkeypatch.setattr(
        desktop,
        "find_active_analysis_job",
        lambda _db: {"status": "running"},
    )
    monkeypatch.setattr(desktop, "load_active_export_batch", lambda _db: None)

    assert "Analysis is still" in active_work_shutdown_block_reason(db)

    monkeypatch.setattr(
        desktop,
        "find_active_analysis_job",
        lambda _db: {"status": "awaiting_input"},
    )
    assert active_work_shutdown_block_reason(db) is None

    monkeypatch.setattr(desktop, "find_active_analysis_job", lambda _db: None)
    monkeypatch.setattr(desktop, "load_active_export_batch", lambda _db: {"status": "running"})
    assert "export batch" in active_work_shutdown_block_reason(db)


def test_desktop_close_stops_backend_before_destroy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    order: list[str] = []
    destroyed = threading.Event()
    closing_handlers = []

    class Event:
        def __iadd__(self, handler):
            closing_handlers.append(handler)
            return self

    class Events:
        def __init__(self) -> None:
            self.closing = Event()

    class Window:
        def __init__(self) -> None:
            self.events = Events()

        def destroy(self) -> None:
            order.append("destroy")
            destroyed.set()

    window = Window()
    fake_webview = types.ModuleType("webview")
    fake_webview.settings = {}
    fake_webview.create_window = lambda *_args, **_kwargs: window

    def start(**_kwargs) -> None:
        assert len(closing_handlers) == 1
        assert closing_handlers[0]() is False
        assert destroyed.wait(2.0)

    fake_webview.start = start
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.os, "name", "nt")

    class Process:
        return_code: int | None = None

        def poll(self) -> int | None:
            return self.return_code

    process = Process()

    def stop_backend() -> None:
        order.append("stop")
        process.return_code = 0

    shutdown_file = tmp_path / "shutdown.flag"
    desktop.run_desktop_shell(process, shutdown_file, stop_backend=stop_backend)

    assert shutdown_file.exists()
    assert order == ["stop", "destroy"]


def test_desktop_close_is_blocked_until_active_work_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    order: list[str] = []
    notices: list[str] = []
    destroyed = threading.Event()
    closing_handlers = []
    active = True

    class Event:
        def __iadd__(self, handler):
            closing_handlers.append(handler)
            return self

    class Events:
        def __init__(self) -> None:
            self.closing = Event()

    class Window:
        def __init__(self) -> None:
            self.events = Events()

        def destroy(self) -> None:
            order.append("destroy")
            destroyed.set()

    window = Window()
    fake_webview = types.ModuleType("webview")
    fake_webview.settings = {}
    fake_webview.create_window = lambda *_args, **_kwargs: window

    def start(**_kwargs) -> None:
        nonlocal active
        assert len(closing_handlers) == 1
        assert closing_handlers[0]() is False
        assert not destroyed.is_set()
        active = False
        assert closing_handlers[0]() is False
        assert destroyed.wait(2.0)

    fake_webview.start = start
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.os, "name", "nt")

    class Process:
        return_code: int | None = None

        def poll(self) -> int | None:
            return self.return_code

    process = Process()

    def stop_backend() -> None:
        order.append("stop")
        process.return_code = 0

    shutdown_file = tmp_path / "shutdown.flag"
    desktop.run_desktop_shell(
        process,
        shutdown_file,
        stop_backend=stop_backend,
        shutdown_blocker=lambda: "Analysis is running." if active else None,
        notify_shutdown_blocked=notices.append,
    )

    assert notices == ["Analysis is running."]
    assert shutdown_file.exists()
    assert order == ["stop", "destroy"]
