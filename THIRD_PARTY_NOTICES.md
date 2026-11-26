# Third-party notices

YapTracker itself is MIT licensed (see `LICENSE`). The Windows app bundles the components below; each keeps its own license. The build copies every bundled package's license files into `licenses/` next to `YapTracker.exe`.

## Fonts

| Font | License | License file |
|---|---|---|
| Barlow Condensed (The Barlow Project Authors) | SIL Open Font License 1.1 | `src/yaptracker/ui/static/fonts/OFL-BarlowCondensed.txt` |
| Nunito Sans (The Nunito Sans Project Authors) | SIL Open Font License 1.1 | `src/yaptracker/ui/static/fonts/OFL-NunitoSans.txt` |
| Noto Emoji pictures (Google LLC), 8 PNGs at 72 px in `src/yaptracker/data/emoji/` for Yap snaps (#121) | SIL Open Font License 1.1 (the repository's license since 2024; its README still names Apache-2.0 for images) | `src/yaptracker/data/emoji/OFL-NotoEmoji.txt` |

## Game data

`src/yaptracker/data/game_lists.json` (hero, map and queue names, #276) is generated at build time by `tools/refresh_game_lists.py` from the [OverFast API](https://github.com/TeKrop/overfast-api) (MIT), which collects them from Overwatch's public website. Overwatch and its hero and map names are trademarks of Blizzard Entertainment; YapTracker only uses the names to correct what OCR read.

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
| PaddleOCR PP-OCRv5 Latin recognizer (`ocr/models/`, ONNX from RapidOCR's model hub) | OCR of umlauts and accents | Apache-2.0 |
| PaddleOCR PP-OCRv5 Latin recognizer, fine-tuned by us on Overwatch chat (`ocr/models/chat_PP-OCRv5_rec.onnx`, its dictionary `chat_dict.txt` from PaddleOCR) | The Chat-trained reading engine | Apache-2.0 (the pretrained weights and the dictionary; trained further with PaddleOCR) |
| ONNX Runtime | Running the OCR models | MIT |
| OpenCV (opencv-python) | Image resizing for OCR | Apache-2.0 |
| Shapely, pyclipper, PyYAML | Used by RapidOCR | BSD-3-Clause, MIT, MIT |
| winsdk | Windows OCR fallback | MIT |
| windows-capture | Window capture (WGC) | MIT |
| PyInstaller bootloader | The `.exe` | GPL-2.0-or-later with the bootloader exception, which allows shipping the app under its own license |

No Blizzard fonts, logos, art or icons are used or shipped.
