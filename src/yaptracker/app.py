"""Start the NiceGUI app: native window on Windows, browser mode with --dev."""

import multiprocessing
import os
import threading

import numpy as np
from nicegui import app, ui
from nicegui.run import io_bound

from yaptracker import demo
from yaptracker.ui import shell

TITLE = "YapTracker"
WINDOW_SIZE = (1280, 800)
DEV_HOST = "0.0.0.0"
DEV_PORT = 8080
SMOKE_TEST_TIMEOUT_S = 90


def _check_ocr() -> bool:
    """The exe must ship working OCR: every engine that runs here reads the demo screenshot."""
    from yaptracker.capture.source import default_chat_region
    from yaptracker.ocr import engine as ocr

    image = demo.screenshot()
    r = default_chat_region(image.width, image.height)
    crop = np.ascontiguousarray(
        np.asarray(image.crop((r.x, r.y, r.x + r.width, r.y + r.height)))[:, :, ::-1]
    )
    for name in ocr.available():
        try:
            engine = ocr.get(name)
        except ocr.OcrUnavailable as reason:
            print(f"smoke test: {name} skipped: {reason}")
            continue
        text = " ".join(line.text for line in engine.read(crop))
        print(f"smoke test: {name} read: {text[:120]}")
        if "WAHOO" not in text.upper():
            return False
    return True


async def _close_window() -> None:
    if not await io_bound(_check_ocr):  # OCR blocks, so off the event loop like in the UI
        print("smoke test: OCR did not read the demo screenshot")
        _give_up()
    # Same path as a user closing the window: NiceGUI sees the window process end and exits 0.
    # (app.shutdown() would also stop uvicorn, which races the closing websocket and can hang.)
    app.native.main_window.destroy()


def _give_up() -> None:
    for child in multiprocessing.active_children():
        child.kill()
    os._exit(1)


def _arm_smoke_test() -> None:
    # A client connecting means the window loaded the page and its websocket is up.
    app.on_connect(_close_window)
    timer = threading.Timer(SMOKE_TEST_TIMEOUT_S, _give_up)
    timer.daemon = True
    timer.start()


def run(*, dev: bool = False, smoke_test: bool = False) -> None:
    shell.register_static_files()
    demo.ENABLED = dev
    if smoke_test:
        _arm_smoke_test()
    common = {
        "title": TITLE,
        # .ico because the native window loads it with LoadImage; browsers take it too.
        "favicon": shell.STATIC_DIR / "yaptracker.ico",
        "dark": True,
        "reload": False,
        "show_welcome_message": dev,
    }
    if dev:
        ui.run(shell.root, host=DEV_HOST, port=DEV_PORT, show=False, **common)
    else:
        # Paint the native window in the night colour before the page loads - no white flash.
        app.native.window_args["background_color"] = "#0d1016"
        ui.run(shell.root, native=True, window_size=WINDOW_SIZE, **common)
