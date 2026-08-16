from __future__ import annotations

import os
from pathlib import Path

# Keep os.add_dll_directory() handles alive for the lifetime of the process.
_DLL_DIRECTORY_HANDLES: list[object] = []


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def configure_windows_cuda_dll_search() -> Path:
    """Make CUDA/cuDNN DLLs placed in the HighlightMiner root discoverable.

    HighlightMiner's documented portable Windows layout keeps the NVIDIA runtime
    DLLs beside run.bat. Python 3.8+ tightened DLL search behavior, so explicitly
    register the repository root rather than relying on the current directory.
    """
    root = project_root()
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


def portable_cuda_core_dlls() -> tuple[str, ...]:
    """Core DLLs expected from the documented CUDA 12 + cuDNN 9 bundle."""
    return (
        "cublas64_12.dll",
        "cublasLt64_12.dll",
        "cudnn64_9.dll",
    )
