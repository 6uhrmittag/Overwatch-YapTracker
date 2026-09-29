# PyInstaller spec: one-folder Windows app in dist/YapTracker/.
# Build (Windows, from the repo root): pyinstaller --noconfirm packaging/yaptracker.spec
from pathlib import Path

import nicegui
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # SPECPATH is injected by PyInstaller
SRC = ROOT / "src"

a = Analysis(
    [str(SRC / "yaptracker" / "__main__.py")],
    pathex=[str(SRC)],
    datas=[
        # NiceGUI serves its own JS/CSS from the package folder.
        (str(Path(nicegui.__file__).parent), "nicegui"),
        (str(SRC / "yaptracker" / "ui" / "static"), "yaptracker/ui/static"),
    ],
    # Both pick their implementation at runtime via importlib.
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("engineio.async_drivers"),
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YapTracker",
    console=False,
    icon=str(SRC / "yaptracker" / "ui" / "static" / "yaptracker.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="YapTracker")
