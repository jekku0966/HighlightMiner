from __future__ import annotations

import pytest

from highlightminer.desktop import resolve_ui_mode, wait_for_server


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
