from __future__ import annotations

import os
import shutil
import subprocess
import sys


def copy_text_to_clipboard(text: str) -> None:
    """Copy text using an operating-system clipboard utility without networking."""
    value = str(text)
    if os.name == "nt":
        subprocess.run(
            ["clip.exe"],
            input=value,
            text=True,
            check=True,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    if sys.platform == "darwin":
        subprocess.run(
            ["pbcopy"],
            input=value,
            text=True,
            check=True,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    if shutil.which("wl-copy"):
        command = ["wl-copy"]
    elif shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        command = ["xsel", "--clipboard", "--input"]
    else:
        raise RuntimeError("No supported local clipboard utility was found.")

    subprocess.run(
        command,
        input=value,
        text=True,
        check=True,
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
