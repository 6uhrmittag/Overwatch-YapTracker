# Third-party notices

YapTracker itself is MIT licensed (see `LICENSE`). The Windows app bundles the components below; each keeps its own license. The build copies every bundled package's license files into `licenses/` next to `YapTracker.exe`.

## Fonts

| Font | License | License file |
|---|---|---|
| Barlow Condensed (The Barlow Project Authors) | SIL Open Font License 1.1 | `src/yaptracker/ui/static/fonts/OFL-BarlowCondensed.txt` |
| Nunito Sans (The Nunito Sans Project Authors) | SIL Open Font License 1.1 | `src/yaptracker/ui/static/fonts/OFL-NunitoSans.txt` |

## Main Python dependencies

| Package | Used for | License |
|---|---|---|
| NiceGUI (incl. Vue, Quasar, Tailwind) | UI | MIT |
| FastAPI, python-socketio, python-engineio | UI server (via NiceGUI) | MIT |
| Starlette, Uvicorn, httpx | UI server (via NiceGUI) | BSD-3-Clause |
| pywebview (+ pythonnet on Windows) | Native window | BSD-3-Clause (pythonnet: MIT) |
| NumPy | Image arrays | BSD-3-Clause and others |
| Pillow | Reading images | MIT-CMU |
| RapidOCR (rapidocr-onnxruntime) incl. PP-OCRv4 models from PaddleOCR | OCR | Apache-2.0 |
| ONNX Runtime | Running the OCR models | MIT |
| OpenCV (opencv-python) | Image resizing for OCR | Apache-2.0 |
| Shapely, pyclipper, PyYAML | Used by RapidOCR | BSD-3-Clause, MIT, MIT |
| winsdk | Windows OCR fallback | MIT |
| PyInstaller bootloader | The `.exe` | GPL-2.0-or-later with the bootloader exception, which allows shipping the app under its own license |

No Blizzard fonts, logos, art or icons are used or shipped.
