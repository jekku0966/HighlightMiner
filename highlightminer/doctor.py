from __future__ import annotations

import subprocess
import sys

from .media import find_executable


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
            ).stdout

            print(
                f"NVENC: "
                f"{'yes' if 'h264_nvenc' in out else 'no (x264 fallback will be used)'}"
            )

        except Exception as exc:
            print(f"NVENC check: failed ({exc})")

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
