# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the Telescope Simulator desktop app. One spec
file for both platforms (single source of truth), gated by sys.platform
where the two builds genuinely differ -- see README's "Packaging standalone
builds" section for the exact commands on each OS.

Windows: run from the repo root (after `pip install -r requirements-build.txt`):
    .venv\\Scripts\\pyinstaller.exe packaging\\telescope_simulator.spec --noconfirm
Produces a --onedir build at dist/TelescopeSimulator/ (folder, not a
single-file exe -- see README for why). Drop a custom icon at
packaging/icon.ico and rebuild to pick it up automatically.

macOS: PyInstaller cannot cross-compile, so this must run ON a Mac (this
repo has no CI set up for it) -- use packaging/build_macos.sh, which runs
this spec then wraps the resulting .app into a .dmg via hdiutil. Targets
arm64 (Apple Silicon) only. Drop a custom icon at packaging/icon.icns and
rebuild to pick it up automatically.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# SPECPATH is injected by PyInstaller as the folder containing this file.
REPO_ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(REPO_ROOT))
from telescope_simulator.version import APP_AUTHOR, APP_BUILD_DATE, APP_BUNDLE_ID, APP_ORGANISATION, APP_VERSION

APP_NAME = "TelescopeSimulator"
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


def _version_tuple(version_str: str):
    # Windows file-version resources need a 4-int tuple; version.py's
    # APP_VERSION is a plain "1.1"-style string, so pad it out here rather
    # than keeping a second, differently-formatted copy in version.py.
    parts = [int(p) for p in version_str.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


# Windows file-properties version resource -- PyInstaller.utils.win32 is
# Windows-only, so both the import and the construction are gated; other
# platforms just pass version=None to EXE() below.
version_info = None
if IS_WINDOWS:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    _file_version = _version_tuple(APP_VERSION)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_file_version, prodvers=_file_version),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", APP_ORGANISATION),
                            StringStruct("FileDescription", "Gaussian Beam Propagation Simulator"),
                            StringStruct("FileVersion", APP_VERSION),
                            StringStruct("ProductVersion", APP_VERSION),
                            StringStruct("ProductName", "Telescope Simulator"),
                            StringStruct("LegalCopyright", f"{APP_AUTHOR}, {APP_ORGANISATION} ({APP_BUILD_DATE})"),
                            StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

_icon_name = "icon.icns" if IS_MACOS else "icon.ico"
_icon_path = REPO_ROOT / "packaging" / _icon_name
icon = str(_icon_path) if _icon_path.exists() else None

a = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    # pyqtgraph bundles some of its own package data (icons/colormaps) that
    # PyInstaller's default import analysis doesn't always pick up -- collect
    # it explicitly rather than discovering a missing-resource bug later.
    datas=collect_data_files("pyqtgraph"),
    hiddenimports=[],
    hookspath=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64" if IS_MACOS else None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# Wraps the onedir COLLECT output into a proper double-clickable .app bundle
# with an Info.plist -- only meaningful on macOS; a no-op on Windows.
if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier=APP_BUNDLE_ID,
        version=APP_VERSION,
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": APP_VERSION,
            "NSHumanReadableCopyright": f"{APP_AUTHOR}, {APP_ORGANISATION} ({APP_BUILD_DATE})",
        },
    )
