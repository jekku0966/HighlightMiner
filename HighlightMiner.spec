# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()

# Streamlit needs a real .py file path at runtime. Bundle app.py as data instead
# of relying only on the PYZ archive so the frozen launcher can hand it to
# Streamlit's normal `run` command.
datas = [
    (str(ROOT / "highlightminer" / "app.py"), "highlightminer"),
]
binaries = []
hiddenimports = []

# These packages use dynamic imports and/or ship frontend/native resources.
# collect_all keeps the first frozen build deliberately conservative; size can
# be optimized after the executable has been validated on clean Windows hosts.
for package in ("streamlit", "faster_whisper", "ctranslate2"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# De-duplicate hidden imports while preserving deterministic ordering.
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    [str(ROOT / "highlightminer" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HighlightMiner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HighlightMiner",
)
