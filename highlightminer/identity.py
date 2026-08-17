from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_SAMPLE_BYTES = 1024 * 1024
_SOURCE_FINGERPRINT_VERSION = "highlightminer-source-v1"


def stable_signature(namespace: str, payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(namespace.encode("utf-8"))
    digest.update(b"\0")
    digest.update(encoded)
    return digest.hexdigest()


def sampled_file_fingerprint(path: str | Path, sample_bytes: int = _SAMPLE_BYTES) -> str:
    """Fingerprint a large local file without hashing every byte.

    Identity combines file size with samples from the beginning, middle, and end.
    This is intended for same-VOD recognition, not adversarial integrity checking.
    """
    file_path = Path(path).expanduser().resolve()
    stat = file_path.stat()
    if not file_path.is_file():
        raise ValueError(f"Not a regular file: {file_path}")

    size = int(stat.st_size)
    sample_bytes = max(4096, int(sample_bytes))
    last_start = max(0, size - sample_bytes)
    middle_start = max(0, min(last_start, (size - sample_bytes) // 2))
    offsets = sorted({0, middle_start, last_start})

    digest = hashlib.sha256()
    digest.update(_SOURCE_FINGERPRINT_VERSION.encode("ascii"))
    digest.update(b"\0")
    digest.update(str(size).encode("ascii"))

    with file_path.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            chunk = handle.read(sample_bytes)
            digest.update(b"\0")
            digest.update(str(offset).encode("ascii"))
            digest.update(b":")
            digest.update(str(len(chunk)).encode("ascii"))
            digest.update(b"\0")
            digest.update(chunk)
    return digest.hexdigest()


def full_file_sha256(path: str | Path, chunk_bytes: int = 1024 * 1024) -> str:
    file_path = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def describe_source(path: str | Path) -> dict[str, Any]:
    file_path = Path(path).expanduser().resolve()
    stat = file_path.stat()
    return {
        "fingerprint": sampled_file_fingerprint(file_path),
        "path": str(file_path),
        "video_name": file_path.name,
        "file_size": int(stat.st_size),
    }
