from __future__ import annotations

import re

DEFAULT_CONTENT_LABEL = "Unsorted"

# Windows forbids these characters in path components. Control characters are
# also invalid, and trailing dots/spaces are rejected by normal Win32 paths.
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalize_content_label(value: str | None) -> str:
    """Return a clean display label, falling back to Unsorted."""
    if value is None:
        return DEFAULT_CONTENT_LABEL
    label = " ".join(str(value).strip().split())
    return label or DEFAULT_CONTENT_LABEL


def content_folder_name(value: str | None) -> str:
    """Convert a content label into a safe cross-platform folder component."""
    label = normalize_content_label(value)
    name = _INVALID_FOLDER_CHARS.sub("_", label)
    name = re.sub(r"_+", "_", name).strip().rstrip(". ")
    if not name:
        name = DEFAULT_CONTENT_LABEL

    # Reserved Windows device names remain reserved even with an extension.
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        name = f"{name}_"

    # Leave enough room for the rest of a normal export path while keeping
    # human-readable Unicode game/category names intact.
    return name[:80].rstrip(". ") or DEFAULT_CONTENT_LABEL
