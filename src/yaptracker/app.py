"""Start the NiceGUI app: native window on Windows, browser mode with --dev."""

import logging
import multiprocessing
import os
import sys
import threading
import time
from collections.abc import Callable

import numpy as np
from nicegui import app, ui
from nicegui.run import io_bound

from yaptracker import autostart as start_with_windows
from yaptracker import config, demo, paths, runtime, system_info
from yaptracker.capture.gdi import QUIET_FRAMES
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.cpu_parts import CPU
from yaptracker.ui import shell

TITLE = "YapTracker"
WINDOW_SIZE = (1280, 800)
DEV_HOST = "0.0.0.0"
DEV_PORT = 8080
SMOKE_TEST_TIMEOUT_S = 90
LATER_NOTE = "unread-chat.json"  # the span of chat frames waiting to be read (#335)
log = logging.getLogger(__name__)


def capture_region(box, height: int, match_running: bool):
    """The calibrated chat box during a match; outside one (menu after a match, map vote,
    before the first match) the strip from it down to the window's bottom edge, where
    Overwatch shows the chat then (#176). Dedup knows lines by their text, not their place."""
    return box if match_running else box.down_to(height)


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


def _watch_for_overwatch(dev: bool) -> None:  # noqa: C901 - split up after v1 (#311)
    """Capture runs by itself from app start: waits for Overwatch, follows it (#16)."""
    from yaptracker.ocr import engine as ocr
    from yaptracker.reading_mode import AFTER, LIGHT

    if config.drop_ocr_gpu():
        log.warning("Use GPU for OCR was on: it's gone in v1 (#219), reading on the CPU")
    ocr.warm_up(config.ocr_engine())  # loaded in the background: nobody waits for it (#219)

    def paused() -> bool:
        return runtime.pause.paused

    runtime.changes = changes = config.change_detector()

    def on_frame(frame) -> None:  # not while paused: the watcher drops those frames (#20)
        size = runtime.window_size
        text_scale = size[1] / 1440 if size else None  # the strip outside matches is taller
        with CPU.part("change detection"):  # where the CPU goes (#302)
            changed = changes.update(frame.image, text_scale)
        if runtime.reader is None:
            return
        mode = runtime.reading.now()  # by the running match's queue (#331)
        if mode == AFTER:  # nothing read now: changed frames wait for the match's end (#335)
            if changed:
                runtime.reader.offer(frame.image, mode)
            return
        if changed or runtime.reader.wants_reread():  # or weak lines on screen (#195)
            runtime.reader.offer(frame.image, mode)  # new text: read, dedup and store it (#108)
        if changed and mode == LIGHT and runtime.reading.light_problem is None:
            runtime.reader.keep_for_tidy(frame.image)  # read again with the best when idle (#336)

    def chat_quiet() -> bool:  # GDI grabs less while nothing new shows (#319)
        reread = runtime.reader is not None and runtime.reader.wants_reread()
        return changes.quiet >= QUIET_FRAMES and not reread

    def on_alive() -> None:
        if runtime.matches is not None:
            runtime.matches.capture_alive()

    def new_match() -> None:  # Ctrl+Alt+M: what the Start match / End match button does (#269)
        if runtime.matches is not None:
            runtime.matches.toggle()

    from yaptracker.game_fps import FpsMeter, overlay_regions
    from yaptracker.ocr import engine as ocr
    from yaptracker.signals import EndScreen, HeroSelect, signal_regions

    # The capture thread reads the signal strips: never wait for a model load there (#219).
    def read_line(image) -> str:
        engine = ocr.ready(config.ocr_engine())
        return engine.read_line(image) if engine is not None else ""

    def read_lines(image) -> list[str]:  # the hero-select corner: map names like ESPERANÇA
        engine, scale = ocr.ready(config.ocr_engine()), runtime.ocr_scale()
        if engine is None:
            return []
        return [line.text for line in engine.read(image, accents=True, scale=scale)]

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

    def chat_started_match() -> bool:
        return runtime.matches is not None and runtime.matches.adoptable()

    hero_select = HeroSelect(
        read_line,
        read_lines,
        hero_select_started,
        match_running=match_running,
        adoptable=chat_started_match,
    )
    end_screen = EndScreen(read_line, match_over)

    def fps_state() -> str:  # one row each of the FPS test (#187), and where in the evening
        playing = runtime.matches is not None and runtime.matches.running  # menus: 60 fps (#302)
        paused = "paused" if runtime.pause.paused else "running"
        return f"{paused}, {'in match' if playing else 'between matches'}"

    fps_meter = FpsMeter(read_line, fps_state)  # Overwatch's own FPS counter, into the log (#212)

    def overwatch_in_front() -> bool:
        window = runtime.watcher.window if runtime.watcher is not None else None
        if window is None or sys.platform != "win32":
            return False
        from yaptracker.capture.window import in_front

        return in_front(window)

    from yaptracker.capture.black import BlackPicture, ScreenFallback

    runtime.black = BlackPicture(overwatch_in_front)  # exclusive Fullscreen, said in words (#217)
    runtime.screen = ScreenFallback(runtime.black, config.screen_capture(),
                                    config.save_screen_capture)  # fmt: skip

    def crops_for(width: int, height: int) -> dict:
        return {**signal_regions(width, height), **overlay_regions(width, height)}

    def on_signals(frame) -> None:  # also while paused: the next match ends a pause (#20)
        if runtime.debug is not None:  # first, so a start/end sample has what was just read
            with CPU.part("debug samples"):
                runtime.debug.on_signals(frame.signals, paused=runtime.pause.paused)
        with CPU.part("match signals"):
            hero_select.update(frame.signals)
            end_screen.update(frame.signals)
            if runtime.window_size is not None:
                fps_meter.update(frame.signals, runtime.window_size[1])
            runtime.black.update(frame.signals.get("overview"))
        if runtime.screen.check(found["window_capture"]) and runtime.watcher is not None:
            runtime.watcher.reopen()  # black window: the screen it's on instead (#236)

    found = {"hwnd": None, "window_capture": False}  # the display line follows (#214)

    def open_source(hwnd: int):
        from yaptracker.capture.wgc import WgcFrameSource, has_rate_setting, windows_build

        found["hwnd"] = hwnd
        build = windows_build()
        found["window_capture"] = has_rate_setting(build) and not runtime.screen.screen
        if found["window_capture"]:
            return WgcFrameSource(hwnd, region_for, signals_for=crops_for)
        from yaptracker.capture.gdi import GdiFrameSource

        if runtime.screen.screen:
            log.info("capture: reading the chat box from the screen with GDI, the window was "
                     "black (#236)")  # fmt: skip
        else:
            log.info("capture: Windows build %d has no rate setting: reading the chat box with "
                     "GDI, only what's on screen (#248)", build)  # fmt: skip
        return GdiFrameSource(hwnd, region_for, signals_for=crops_for, quiet=chat_quiet)

    def region_for(width: int, height: int):
        if found["hwnd"] is not None:
            hwnd, found["hwnd"] = found["hwnd"], None
            system_info.game_found(hwnd, width, height)
        runtime.window_size = (width, height)  # the Live view hints when this changes (#84)
        running = runtime.matches is None or runtime.matches.running
        return capture_region(config.chat_region(width, height), height, running)

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
        from yaptracker.capture.window import find_overwatch

        return CaptureWatcher(find_overwatch, open_source, on_frame, **common)

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

        def save_chat() -> None:
            if runtime.debug is not None:
                runtime.debug.save_chat()

        def lookup() -> None:  # the window to the front; the UI focuses "Who's that?" (#27)
            from yaptracker.single_instance import focus_own_window

            runtime.lookup_requested = time.monotonic()
            focus_own_window()

        actions = {"pause": runtime.pause.toggle, "new_match": new_match, "save": save_chat,
                   "lookup": lookup}  # fmt: skip

        def bind_hotkeys(on: bool = True) -> None:
            """(Re)registers the keys from Settings; off while Settings listens for a new one."""
            if runtime.hotkeys is not None:
                runtime.hotkeys.stop()
                runtime.hotkeys = None
            if on:
                combos = config.hotkeys()
                runtime.hotkeys = HotkeyListener({combos[a]: f for a, f in actions.items()})
                runtime.hotkeys.start()

        runtime.bind_hotkeys = bind_hotkeys
        app.on_startup(bind_hotkeys)
        app.on_shutdown(lambda: bind_hotkeys(False))


def debug_part(chat_read: Callable, *read) -> None:
    """The reader's debug samples count as debug samples, not reading (#302)."""
    with CPU.part("debug samples"):
        chat_read(*read)


def _open_store() -> Callable[[], None]:
    """The database opens with the app (the smoke test too: it proves SQLite + FTS5 in the exe).

    Returns the close function; run() registers it last, after capture has stopped writing.
    """
    from yaptracker import later
    from yaptracker.capture.health import CaptureHealth
    from yaptracker.debug import DebugSamples
    from yaptracker.familiar import FamiliarFaces
    from yaptracker.lines import LinePictures
    from yaptracker.matches import MatchTracker
    from yaptracker.players import PlayerMatcher
    from yaptracker.reader import ChatReader
    from yaptracker.reading_mode import AFTER, ReadingMode
    from yaptracker.store.backups import DailyBackup
    from yaptracker.store.repo import Store

    def missed_end() -> None:
        if runtime.debug is not None:
            runtime.debug.match_event("missed-end")

    def missed_start(source: str) -> None:  # the minutes before: was a hero select there? (#170)
        if runtime.debug is not None:
            runtime.debug.match_event(f"missed-start-{source}")

    def open_store() -> None:
        runtime.debug = DebugSamples(paths.debug_dir(), config.debug_samples)
        runtime.debug.clean_up()  # 14 days / 1 GB, also after a long break
        runtime.pictures = LinePictures(paths.lines_dir(), config.line_pictures)
        runtime.pictures.clean_up()  # 2 GB, oldest months first
        runtime.store = Store.open()
        runtime.backups = DailyBackup(
            runtime.store.backup_to,
            paths.backup_dir(),
            busy=lambda: runtime.watcher is not None and runtime.watcher.state == "capturing",
        )
        runtime.backups.start()  # now (first start of the day), or once Overwatch is closed
        runtime.matches = MatchTracker(runtime.store, runtime.pause, on_missed_end=missed_end,
                                       on_missed_start=missed_start)  # fmt: skip
        runtime.health = CaptureHealth(runtime.store)
        runtime.familiar = FamiliarFaces(runtime.store, config.identity)
        runtime.players = PlayerMatcher(
            runtime.store,
            config.identity,
            on_shaky=lambda name: runtime.debug.save_chat("new-player"),
        )
        runtime.reading = ReadingMode(
            lambda: runtime.matches,
            lambda: config.reading("competitive"),
            lambda: config.reading("other"),
            config.ocr_engine,
        )
        note = paths.data_dir() / LATER_NOTE
        if (lost := later.lost_span(note)) is not None:  # the app crashed or was killed (#335)
            log.warning("chat frames kept for after the match were lost: a gap record")
            runtime.store.close_gap(runtime.store.open_gap(lost[0], "deferred_lost"), lost[1])

        def capturing() -> bool:
            return runtime.watcher is not None and runtime.watcher.state == "capturing"

        runtime.reader = ChatReader(
            lambda image: runtime.reading.read(image, runtime.ocr_scale()),
            runtime.store,
            runtime.matches,
            identity=config.identity,
            colours=config.channel_colours,
            save_colours=config.save_channel_colours,
            paused=lambda: runtime.pause.paused,
            on_read=lambda *read: debug_part(runtime.debug.chat_read, *read),
            pictures=runtime.pictures,
            players=runtime.players,
            on_player=runtime.familiar.heard,
            min_gap_s=config.read_every_s(),
            modes=runtime.reading.take_counts,
            later=later.LaterFrames(lambda: runtime.reader.min_gap_s, note),
            read_kept=lambda image, mode: runtime.reading.read(image, runtime.ocr_scale(), mode),
            deferring=lambda: capturing() and runtime.reading.now() == AFTER,
            idle=lambda: not capturing() or not runtime.matches.running,
        )
        runtime.reader.start()

    def close_store() -> None:
        if runtime.backups is not None:
            runtime.backups.stop()
        if runtime.reader is not None:
            runtime.reader.stop()  # capture has stopped; the last frame is stored first
        if runtime.health is not None:
            runtime.health.stop()
        if runtime.matches is not None:
            runtime.matches.stop()
        if runtime.store is not None:
            runtime.store.close()

    app.on_startup(open_store)
    return close_store


def _keep_window_place(background: bool) -> None:
    """Opens where you left it (#253): restore the saved place, then save every change."""
    if sys.platform != "win32":
        return
    from yaptracker import single_instance, window_place

    stop = threading.Event()
    threading.Thread(target=window_place.keep, args=(single_instance.own_window, background, stop),
                     name="window place", daemon=True).start()  # fmt: skip
    app.on_shutdown(stop.set)


def native_window_args(background: bool) -> dict:
    """pywebview's window settings (they don't apply in --dev's browser)."""
    return {
        # Paint the window in the night colour before the page loads - no white flash.
        "background_color": "#0d1016",
        # Started with Windows: sit in the taskbar and wait for Overwatch (#45).
        "minimized": background,
        # pywebview turns text selection off by default: chat couldn't be copied (#221).
        "text_select": True,
    }


def run(
    *,
    dev: bool = False,
    smoke_test: bool = False,
    background: bool = False,
    autostart: bool | None = None,
) -> None:
    shell.register_static_files()
    demo.ENABLED = dev
    system_info.log_at_start()  # to compare numbers between PCs (#214)
    config.on_save.append(system_info.log_settings)
    close_store = _open_store()
    if not (dev or smoke_test):
        start_with_windows.apply_at_start(autostart)
        _keep_window_place(background)
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
        app.native.window_args.update(native_window_args(background))
        ui.run(shell.root, native=True, window_size=WINDOW_SIZE, **common)
