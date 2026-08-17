from __future__ import annotations

import ctypes
import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

UI_HOST = "127.0.0.1"
UI_PORT = 8501
UI_URL = f"http://{UI_HOST}:{UI_PORT}"
_VALID_UI_MODES = {"desktop", "browser", "server"}


def resolve_ui_mode(*, browser_requested: bool = False, platform_name: str | None = None) -> str:
    """Resolve how the local Streamlit UI should be presented.

    Windows defaults to the native pywebview shell. Browser mode remains an
    explicit troubleshooting/development fallback. Server mode is intentionally
    private-ish plumbing used by automated smoke tests.
    """
    if browser_requested:
        return "browser"

    override = os.environ.get("HIGHLIGHTMINER_UI_MODE", "").strip().lower()
    if override:
        if override not in _VALID_UI_MODES:
            allowed = ", ".join(sorted(_VALID_UI_MODES))
            raise ValueError(f"Invalid HIGHLIGHTMINER_UI_MODE={override!r}; expected one of: {allowed}")
        return override

    platform_name = platform_name or os.name
    return "desktop" if platform_name == "nt" else "browser"


def wait_for_server(process: Any, *, url: str = UI_URL, timeout: float = 60.0) -> None:
    """Wait until Streamlit answers locally or fail if the child exits."""
    deadline = time.monotonic() + max(1.0, float(timeout))
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"Streamlit exited before the UI became ready (exit code {return_code}).")

        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=1.0) as response:
                if int(getattr(response, "status", 0)) == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc

        time.sleep(0.25)

    detail = f" Last connection error: {last_error}" if last_error else ""
    raise TimeoutError(f"HighlightMiner UI did not become ready at {url} within {timeout:.0f} seconds.{detail}")


def open_system_browser(url: str = UI_URL) -> None:
    if not webbrowser.open(url, new=2):
        raise RuntimeError(f"Could not open the system browser for {url}")


def desktop_runtime_probe() -> None:
    """Import the Windows pywebview backend without creating a GUI window."""
    if os.name != "nt":
        return
    import webview  # noqa: F401
    import webview.platforms.edgechromium  # noqa: F401
    import webview.platforms.winforms  # noqa: F401


def run_desktop_shell(process: Any, shutdown_file: Path, *, url: str = UI_URL) -> None:
    """Display Streamlit inside a native Windows pywebview/WebView2 window."""
    if os.name != "nt":
        raise RuntimeError("The native HighlightMiner desktop shell is currently Windows-only.")

    import webview

    # Keep normal links from turning the embedded app into a general-purpose
    # browser. HighlightMiner itself remains loaded from loopback only.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    window = webview.create_window(
        "HighlightMiner",
        url,
        width=1440,
        height=900,
        min_size=(960, 640),
        resizable=True,
        background_color="#0D1117",
        text_select=True,
    )

    stop_watcher = threading.Event()

    def watch_backend() -> None:
        while not stop_watcher.wait(0.25):
            if shutdown_file.exists() or process.poll() is not None:
                try:
                    window.destroy()
                except Exception:
                    pass
                return

    watcher = threading.Thread(target=watch_backend, name="HighlightMiner-ui-watch", daemon=True)
    watcher.start()
    try:
        # Streamlit requires a modern browser engine. Force WebView2 rather than
        # silently falling back to the legacy MSHTML renderer.
        webview.start(gui="edgechromium", debug=False, private_mode=True)
    finally:
        stop_watcher.set()
        watcher.join(timeout=1.0)


def show_native_error(title: str, message: str) -> None:
    """Show launch failures even when the packaged console is hidden."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass
