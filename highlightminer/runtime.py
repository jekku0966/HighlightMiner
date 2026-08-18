from __future__ import annotations

import os
import sys
from pathlib import Path

# Keep os.add_dll_directory() handles alive for the lifetime of the process.
_DLL_DIRECTORY_HANDLES: list[object] = []


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller-frozen application."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory containing the user-facing HighlightMiner application.

    In source/development mode this is the repository root. In a PyInstaller
    onedir build this is the folder containing HighlightMiner.exe. User-editable
    files and portable third-party runtimes live here.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """Directory containing files bundled inside the frozen application."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)).resolve()
    return Path(__file__).resolve().parent.parent


def bundled_path(*parts: str) -> Path:
    """Resolve a path to a file included as PyInstaller bundle data."""
    return bundle_root().joinpath(*parts)


def project_root() -> Path:
    """Backward-compatible alias for the user-facing app root."""
    return app_root()


def portable_cuda_core_dlls() -> tuple[str, ...]:
    """Core DLLs expected from the documented CUDA 12 + cuDNN 9 bundle."""
    return (
        "cublas64_12.dll",
        "cublasLt64_12.dll",
        "cudnn64_9.dll",
    )


def portable_cuda_root() -> Path:
    """Resolve the local directory that should provide portable CUDA DLLs.

    Source checkouts prefer the dedicated runtime/cuda directory when the core
    runtime is present there. Existing root-folder source layouts remain a
    backward-compatible fallback. Frozen builds keep the DLLs beside the EXE.
    """
    root = app_root()
    if is_frozen():
        return root

    dedicated = root / "runtime" / "cuda"
    if all((dedicated / name).is_file() for name in portable_cuda_core_dlls()):
        return dedicated
    return root


def configure_windows_cuda_dll_search() -> Path:
    """Make HighlightMiner's selected CUDA/cuDNN directory discoverable."""
    root = portable_cuda_root()
    if os.name != "nt":
        return root

    root_text = str(root)

    # Some libraries still consult PATH directly.
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    if root_text.lower() not in {p.lower() for p in path_parts if p}:
        os.environ["PATH"] = root_text + os.pathsep + os.environ.get("PATH", "")

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        try:
            handle = add_dll_directory(root_text)
            _DLL_DIRECTORY_HANDLES.append(handle)
        except OSError:
            # The caller/doctor will provide the useful failure information.
            pass

    return root
