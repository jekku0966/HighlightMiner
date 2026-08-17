from __future__ import annotations

import ctypes
import os
import subprocess
import sys

from .media import find_executable
from .runtime import (
    configure_windows_cuda_dll_search,
    portable_cuda_core_dlls,
)

_WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _webview2_runtime_version() -> str | None:
    if os.name != "nt":
        return None

    try:
        import winreg
    except ImportError:
        return None

    locations = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}"),
    )
    for hive, path in locations:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        version = str(value or "").strip()
        if version and version != "0.0.0.0":
            return version
    return None


def run_doctor() -> int:
    print("HighlightMiner doctor\n")
    print(f"Python: {sys.version.split()[0]}")

    ok = True
    found: dict[str, str | None] = {}

    for exe in ("ffmpeg", "ffprobe"):
        path = find_executable(exe)
        found[exe] = path
        print(f"{exe}: {path or 'MISSING'}")
        ok = ok and bool(path)

    ffmpeg = found["ffmpeg"]

    if ffmpeg:
        try:
            out = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                check=True,
                shell=False,
            ).stdout

            print(
                f"NVENC: "
                f"{'yes' if 'h264_nvenc' in out else 'no (x264 fallback will be used)'}"
            )

        except Exception as exc:
            print(f"NVENC check: failed ({exc})")

    if os.name == "nt":
        try:
            import webview  # noqa: F401

            print("pywebview desktop shell: yes")
        except Exception as exc:
            print(f"pywebview desktop shell: FAILED ({exc})")
            ok = False

        webview2_version = _webview2_runtime_version()
        if webview2_version:
            print(f"WebView2 Runtime: {webview2_version}")
        else:
            print("WebView2 Runtime: MISSING")
            ok = False

    cuda_root = configure_windows_cuda_dll_search()
    cuda_dlls_ok = True

    if os.name == "nt":
        print(f"Portable CUDA DLL root: {cuda_root}")
        for dll_name in portable_cuda_core_dlls():
            dll_path = cuda_root / dll_name
            if not dll_path.is_file():
                print(f"  {dll_name}: MISSING")
                cuda_dlls_ok = False
                continue
            try:
                ctypes.WinDLL(str(dll_path))
                print(f"  {dll_name}: yes")
            except OSError as exc:
                print(f"  {dll_name}: found but could not be loaded ({exc})")
                cuda_dlls_ok = False

    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()

        print(f"CTranslate2: {getattr(ctranslate2, '__version__', '?')}")
        print(f"CUDA devices visible to CTranslate2: {count}")

        if count:
            print(
                f"CUDA compute types: "
                f"{sorted(ctranslate2.get_supported_compute_types('cuda'))}"
            )
            if os.name == "nt" and not cuda_dlls_ok:
                print("GPU Whisper runtime: NOT READY (portable CUDA/cuDNN DLLs missing or unloadable)")
                ok = False
            else:
                print("GPU Whisper runtime: core CUDA/cuDNN DLLs loadable")

    except Exception as exc:
        print(f"CTranslate2/CUDA check failed: {exc}")
        ok = False

    try:
        import faster_whisper

        print(
            f"faster-whisper: "
            f"{getattr(faster_whisper, '__version__', '?')}"
        )

    except Exception as exc:
        print(f"faster-whisper import failed: {exc}")
        ok = False

    print("\nResult:", "looks good" if ok else "needs attention")

    return 0 if ok else 1
