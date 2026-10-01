"""Start the NiceGUI app: native window on Windows, browser mode with --dev."""

import multiprocessing
import os
import sys
import threading
from collections.abc import Callable

import numpy as np
from nicegui import app, ui
from nicegui.run import io_bound

from yaptracker import autostart as start_with_windows
from yaptracker import config, demo, paths, runtime
from yaptracker.capture.watcher import CaptureWatcher
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


def _watch_for_overwatch(dev: bool) -> None:
    """Capture runs by itself from app start: waits for Overwatch, follows it (#16)."""

    def paused() -> bool:
        return runtime.pause.paused

    runtime.changes = changes = config.change_detector()

    def on_frame(frame) -> None:
        # Changed bands go to OCR once the pipeline exists (#18); a change can start a match.
        if changes.update(frame.image) and runtime.matches is not None:
            runtime.matches.chat_changed()

    def on_alive() -> None:
        if runtime.matches is not None:
            runtime.matches.capture_alive()

    def new_match() -> None:
        if runtime.matches is not None:
            runtime.matches.new_match()

    from yaptracker.ocr import engine as ocr
    from yaptracker.signals import EndScreen, HeroSelect, signal_regions

    def read_line(image) -> str:
        return ocr.get(config.ocr_engine()).read_line(image)

    def read_lines(image) -> list[str]:
        return [line.text for line in ocr.get(config.ocr_engine()).read(image)]

    def hero_select_started(mode: str | None, map_name: str | None) -> None:
        if runtime.matches is not None:
            runtime.matches.new_match(source="heroselect", mode=mode, map_name=map_name)
        if runtime.debug is not None:
            runtime.debug.match_event("start")

    def match_running() -> bool:
        return runtime.matches is not None and runtime.matches.running

    def match_over(outcome: str | None) -> None:
        if runtime.matches is not None:
            was_running = runtime.matches.running
            runtime.matches.end_match(outcome=outcome)
            if was_running and runtime.debug is not None:
                runtime.debug.match_event("end")

    hero_select = HeroSelect(
        read_line, read_lines, hero_select_started, match_running=match_running
    )
    end_screen = EndScreen(read_line, match_over)

    def on_signals(frame) -> None:  # also while paused: the next match ends a pause (#20)
        if runtime.debug is not None:  # first, so a start/end sample has what was just read
            runtime.debug.on_signals(frame.signals, paused=runtime.pause.paused)
        hero_select.update(frame.signals)
        end_screen.update(frame.signals)

    def region_for(width: int, height: int):
        runtime.window_size = (width, height)  # the Live view hints when this changes (#84)
        return config.chat_region(width, height)

    def make_watcher() -> CaptureWatcher:
        common = {
            "paused": paused,
            "on_alive": on_alive,
            "health": runtime.health,
            "on_signals": on_signals,
        }
        if dev:
            runtime.window_size = (2560, 1440)  # the demo stands in for a 1440p Overwatch window
            return CaptureWatcher(lambda: 1, lambda _: demo.DemoFrameSource(), on_frame, **common)
        from yaptracker.capture.wgc import WgcFrameSource
        from yaptracker.capture.window import find_overwatch

        return CaptureWatcher(
            find_overwatch,
            lambda hwnd: WgcFrameSource(hwnd, region_for, signals_for=signal_regions),
            on_frame,
            **common,
        )

    if not dev and sys.platform != "win32":
        return  # native mode only exists on Windows; Linux uses --dev

    def start_capture() -> None:  # after the store is open: gaps and matches need it
        if not dev and runtime.health is not None:
            from yaptracker.capture import process
            from yaptracker.capture.window import find_overwatch

            if find_overwatch() is not None:  # the game was there before us (#99)
                last = runtime.store.latest_session() if runtime.store else None
                runtime.health.started_late(process.started_at(), last[1] if last else None)
        runtime.watcher = make_watcher()
        runtime.watcher.start()

    def stop_capture() -> None:
        if runtime.watcher is not None:
            runtime.watcher.stop()

    app.on_startup(start_capture)
    app.on_shutdown(stop_capture)
    if not dev:
        from yaptracker.hotkeys import HotkeyListener

        hotkeys = HotkeyListener(
            {runtime.PAUSE_HOTKEY: runtime.pause.toggle, runtime.NEW_MATCH_HOTKEY: new_match}
        )
        app.on_startup(hotkeys.start)
        app.on_shutdown(hotkeys.stop)


def _open_store() -> Callable[[], None]:
    """The database opens with the app (the smoke test too: it proves SQLite + FTS5 in the exe).

    Returns the close function; run() registers it last, after capture has stopped writing.
    """
    from yaptracker.capture.health import CaptureHealth
    from yaptracker.debug import DebugSamples
    from yaptracker.matches import MatchTracker
    from yaptracker.store.repo import Store

    def missed_end() -> None:
        if runtime.debug is not None:
            runtime.debug.match_event("missed-end")

    def open_store() -> None:
        runtime.debug = DebugSamples(paths.debug_dir(), config.debug_samples)
        runtime.debug.clean_up()  # 14 days / 1 GB, also after a long break
        runtime.store = Store.open()
        runtime.matches = MatchTracker(runtime.store, runtime.pause, on_missed_end=missed_end)
        runtime.health = CaptureHealth(runtime.store)

    def close_store() -> None:
        if runtime.health is not None:
            runtime.health.stop()
        if runtime.matches is not None:
            runtime.matches.stop()
        if runtime.store is not None:
            runtime.store.close()

    app.on_startup(open_store)
    return close_store


def run(
    *,
    dev: bool = False,
    smoke_test: bool = False,
    background: bool = False,
    autostart: bool | None = None,
) -> None:
    shell.register_static_files()
    demo.ENABLED = dev
    close_store = _open_store()
    if not (dev or smoke_test):
        start_with_windows.apply_at_start(autostart)
    _watch_for_overwatch(dev)
    app.on_shutdown(close_store)
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
        # Started with Windows: sit in the taskbar and wait for Overwatch (#45).
        app.native.window_args["minimized"] = background
        ui.run(shell.root, native=True, window_size=WINDOW_SIZE, **common)
