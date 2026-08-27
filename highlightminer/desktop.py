from __future__ import annotations

import ctypes
import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from .analysis_jobs import find_active_analysis_job
from .export_queue import load_active_export_batch

UI_HOST = "127.0.0.1"
UI_PORT = 8501
UI_URL = f"http://{UI_HOST}:{UI_PORT}"
_VALID_UI_MODES = {"desktop", "browser", "server"}


def active_work_shutdown_block_reason(db_path: str | Path) -> str | None:
    """Explain why stopping the shared UI process would interrupt live work."""
    analysis_job = find_active_analysis_job(db_path)
    if analysis_job is not None and analysis_job["status"] != "awaiting_input":
        return (
            "Analysis is still starting or running. HighlightMiner cannot safely cancel "
            "this stage, so wait for it to finish or reach the model choice before exiting."
        )

    if load_active_export_batch(db_path) is not None:
        return (
            "An export batch is still running. HighlightMiner cannot safely cancel FFmpeg "
            "mid-export, so wait for the batch to finish before exiting."
        )

    return None


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


def run_desktop_shell(
    process: Any,
    shutdown_file: Path,
    *,
    url: str = UI_URL,
    stop_backend: Callable[[], None] | None = None,
    shutdown_blocker: Callable[[], str | None] | None = None,
    notify_shutdown_blocked: Callable[[str], None] | None = None,
) -> None:
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
    shutdown_started = threading.Event()
    backend_stopped = threading.Event()
    shutdown_lock = threading.Lock()

    def finish_orderly_shutdown() -> None:
        try:
            if stop_backend is not None and process.poll() is None:
                stop_backend()
        finally:
            backend_stopped.set()
            try:
                window.destroy()
            except Exception:
                pass

    def request_orderly_shutdown() -> bool:
        with shutdown_lock:
            if shutdown_started.is_set():
                return True
            if shutdown_blocker is not None:
                try:
                    block_reason = shutdown_blocker()
                except Exception as exc:
                    block_reason = (
                        "HighlightMiner could not verify whether background work is active "
                        f"({type(exc).__name__}: {exc}). Wait and try exiting again."
                    )
                if block_reason:
                    notifier = notify_shutdown_blocked or (
                        lambda message: show_native_warning("HighlightMiner is still working", message)
                    )
                    notifier(block_reason)
                    return False
            shutdown_started.set()
            try:
                shutdown_file.touch()
            except OSError:
                pass
            threading.Thread(
                target=finish_orderly_shutdown,
                name="HighlightMiner-ui-stop",
                daemon=True,
            ).start()
            return True

    def on_closing() -> bool | None:
        # Keep WebView2 alive until Streamlit has stopped so Windows does not
        # report a reset connection while asyncio is tearing down its socket.
        if backend_stopped.is_set() or process.poll() is not None:
            return None
        request_orderly_shutdown()
        return False

    window.events.closing += on_closing

    def watch_backend() -> None:
        while not stop_watcher.wait(0.25):
            if process.poll() is not None:
                if shutdown_started.is_set():
                    return
                backend_stopped.set()
                try:
                    window.destroy()
                except Exception:
                    pass
                return
            if shutdown_file.exists():
                if request_orderly_shutdown():
                    return
                try:
                    shutdown_file.unlink(missing_ok=True)
                except OSError:
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


def show_native_warning(title: str, message: str) -> None:
    """Show a native warning when closing would interrupt active work."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x30)
    except Exception:
        pass
