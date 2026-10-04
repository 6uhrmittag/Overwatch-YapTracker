# PyInstaller spec: one-folder Windows app in dist/YapTracker/.
# Build (Windows, from the repo root): pyinstaller --noconfirm packaging/yaptracker.spec
import shutil
from importlib.metadata import distributions
from pathlib import Path

import nicegui
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # SPECPATH is injected by PyInstaller
SRC = ROOT / "src"

a = Analysis(
    [str(SRC / "yaptracker" / "__main__.py")],
    pathex=[str(SRC)],
    datas=[
        # NiceGUI serves its own JS/CSS from the package folder.
        (str(Path(nicegui.__file__).parent), "nicegui"),
        (str(SRC / "yaptracker" / "ui" / "static"), "yaptracker/ui/static"),
        (str(SRC / "yaptracker" / "data"), "yaptracker/data"),  # game lists (#276)
        (str(SRC / "yaptracker" / "ocr" / "models"), "yaptracker/ocr/models"),  # umlauts, #118
        # OCR models (.onnx) and config.yaml
        *collect_data_files("rapidocr_onnxruntime"),
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

# Licenses next to the exe: ours, the notices, and every bundled package's own license files.
APP = Path(DISTPATH) / "YapTracker"  # DISTPATH is injected by PyInstaller
for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    shutil.copy(ROOT / name, APP / name)
for dist in distributions():
    files = [f for f in dist.files or [] if f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
    for f in files:
        target = APP / "licenses" / dist.metadata["Name"] / f.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f.locate(), target)
