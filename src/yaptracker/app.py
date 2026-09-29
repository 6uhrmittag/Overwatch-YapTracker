"""Start the NiceGUI app: native window on Windows, browser mode with --dev."""

import multiprocessing
import os
import threading

from nicegui import app, ui

from yaptracker.ui import shell

TITLE = "YapTracker"
WINDOW_SIZE = (1280, 800)
DEV_HOST = "0.0.0.0"
DEV_PORT = 8080
SMOKE_TEST_TIMEOUT_S = 90


def _close_window() -> None:
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
    if smoke_test:
        _arm_smoke_test()
    common = {
        "title": TITLE,
        "favicon": shell.STATIC_DIR / "logo.svg",
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
