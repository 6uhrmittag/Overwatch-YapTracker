"""Capture runs by itself from app start: waits for Overwatch, follows it (#16). What used to be one
long function in app.py (complexity 83), split into named steps with the same behaviour (#311):
the chat path (frames -> change detection -> the reader), the match signals (hero select, end
screen, Overwatch's FPS box), the black-window fallback (#217, #236, #560), the capture source
(window or screen, its rate, stalls, #506), the CPU line (#302) and the hotkeys (#328).

The small decisions are plain functions at the top, tested on their own.
"""

import logging
import sys
import threading
import time
from collections.abc import Callable

from nicegui import app

from yaptracker import config, demo, runtime, side_work, system_info
from yaptracker.capture.gdi import QUIET_FRAMES
from yaptracker.capture.watcher import MATCH_STALL_S, STALL_S, CaptureWatcher
from yaptracker.cpu_parts import CPU

log = logging.getLogger(__name__)


def capture_region(box, height: int, match_running: bool):
    """The calibrated chat box during a match; outside one (menu after a match, map vote,
    before the first match) the strip from it down to the window's bottom edge, where
    Overwatch shows the chat then (#176). Dedup knows lines by their text, not their place."""
    return box if match_running else box.down_to(height)


def start_watcher(note_a_late_start: Callable[[], None], make_watcher: Callable):
    """The capture watcher always starts (#457): checking whether the game was there before us
    (#99) writes a gap, and that may fail."""
    try:
        note_a_late_start()
    except Exception:
        log.exception("couldn't check whether Overwatch started before YapTracker")
    watcher = make_watcher()
    watcher.start()
    return watcher


def in_match(matches) -> bool:
    """A match is running; no match tracker yet means none."""
    return matches is not None and matches.running


def in_match_or_unknown(matches) -> bool:
    """For the capture's box and rate: without a match tracker, as in a match (the chat box)."""
    return matches is None or matches.running


def fps_state_words(paused: bool, playing: bool) -> str:
    """One row each of the FPS test (#187), and where in the evening (menus: 60 fps, #302)."""
    return f"{'paused' if paused else 'running'}, {'in match' if playing else 'between matches'}"


def cpu_state_words(capturing: bool, paused: bool, playing: bool) -> str:
    """The same words in the cpu parts line (#351)."""
    if not capturing:
        return "no game"
    if paused:
        return "paused"
    return "in match" if playing else "between matches"


def stall_limit(running: bool, in_front: bool) -> float:
    """A game in a match always draws (#506); menus send few pictures."""
    return MATCH_STALL_S if running and in_front else STALL_S


def screen_match(matches) -> int | None:
    """The running match for the screen fallback's tries (#560): None between matches."""
    return matches.match_id if in_match(matches) else None


def game_ran_for(started: float | None, now: float) -> float | None:
    """How long Overwatch already ran when YapTracker found it: not a starting game, so black
    means black (#560). None: its start is unknown."""
    return None if started is None else max(0.0, now - started)


class CaptureWiring:
    """Everything capture needs, made once at app start; `install` hooks it into the app."""

    def __init__(self, dev: bool) -> None:
        from yaptracker.capture.black import BlackPicture, ScreenFallback
        from yaptracker.capture.wgc import CaptureRate
        from yaptracker.game_fps import FpsMeter
        from yaptracker.signals import EndScreen, HeroSelect, SameLook

        self.dev = dev
        runtime.changes = self.changes = config.change_detector()
        self.found = {"hwnd": None, "window_capture": False}  # the display line follows (#214)
        self.ran_before = 0.0  # Overwatch already ran this long when YapTracker started
        self._fps_mode_failed = threading.Event()
        self._ticking = threading.Event()  # a "no game" minute has no part adding CPU: tick
        # A menu that stands still isn't read again every look (#453). Not the info corner: its
        # second looks want another read of the same picture (#342); nor the FPS box, it changes.
        signal_line = SameLook(self.read_line)
        self.hero_select = HeroSelect(
            signal_line,
            self.read_lines,
            self.hero_select_started,
            match_running=lambda: in_match(runtime.matches),
            adoptable=lambda: runtime.matches is not None and runtime.matches.adoptable(),
            on_info=self.hero_select_info,
            read_band=self.read_line,
        )
        self.end_screen = EndScreen(signal_line, self.match_over, on_map=self.end_map)
        self.fps_meter = FpsMeter(self.read_line, self.fps_state, mode=self.fps_mode)  # (#212)
        runtime.black = BlackPicture(self.overwatch_in_front, window_age=self.window_age)  # #217
        runtime.screen = ScreenFallback(runtime.black, remembered=config.screen_capture(),
                                        remember=config.save_screen_capture)  # fmt: skip
        # 2 frames a second, in and between (#350, #115)
        self.rate = CaptureRate(lambda: in_match_or_unknown(runtime.matches), self.reopen)

    # --- the chat path ---------------------------------------------------------------------

    def on_frame(self, frame) -> None:
        """Not while paused: the watcher drops those frames (#20)."""
        from yaptracker.reading_mode import AFTER, LIGHT

        size = runtime.window_size
        text_scale = size[1] / 1440 if size else None  # the strip outside matches is taller
        with CPU.part("change detection"):  # where the CPU goes (#302)
            changed = self.changes.update(frame.image, text_scale)
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

    def chat_quiet(self) -> bool:
        """GDI grabs less while nothing new shows (#319)."""
        reread = runtime.reader is not None and runtime.reader.wants_reread()
        return self.changes.quiet >= QUIET_FRAMES and not reread

    # --- the match signals -----------------------------------------------------------------
    # The capture thread reads the signal strips: never wait for a model load there (#219).

    def read_line(self, image) -> str:
        from yaptracker.ocr import engine as ocr

        engine = ocr.ready(config.ocr_engine())
        return engine.read_line(image) if engine is not None else ""

    def read_lines(self, image) -> list[str]:
        """The hero-select corner: map names like ESPERANÇA."""
        from yaptracker.ocr import engine as ocr

        engine, scale = ocr.ready(config.ocr_engine()), runtime.ocr_scale()
        if engine is None:
            return []
        return [line.text for line in engine.read(image, accents=True, scale=scale)]

    def hero_select_started(self, mode: str | None, map_name: str | None) -> None:
        if runtime.matches is not None:
            runtime.matches.new_match(source="heroselect", mode=mode, map_name=map_name)
        if runtime.debug is not None:
            runtime.debug.match_event("start")

    def hero_select_info(self, mode: str | None, map_name: str | None) -> None:  # (#342)
        if runtime.matches is not None:
            runtime.matches.learn_info(mode, map_name)

    def match_over(self, outcome: str | None) -> None:
        if runtime.matches is not None:
            was_running = runtime.matches.running
            runtime.matches.end_match(outcome=outcome)
            if was_running and runtime.debug is not None:
                runtime.debug.match_event("end")

    def end_map(self, map_name: str) -> None:
        """For a match without a map: the "VICTORY <MAP>" banner (#383)."""
        taken = runtime.matches is not None and runtime.matches.end_map(map_name)
        if taken and runtime.debug is not None:  # proof for the next evening's check
            runtime.debug.match_event("end-map")

    def fps_state(self) -> str:
        return fps_state_words(runtime.pause.paused, in_match(runtime.matches))

    def fps_mode(self, state: str, since: float) -> str | None:
        """Who read chat in that minute (#444)."""
        reading = runtime.reading
        if state != "running, in match" or reading is None:  # the minute's own state
            return None
        try:
            return reading.read_in(since)
        except Exception:  # a label never stops the capture
            if not self._fps_mode_failed.is_set():
                self._fps_mode_failed.set()
                log.exception("game fps: which reader read is unknown (said once)")
            return None

    def crops_for(self, width: int, height: int) -> dict:
        from yaptracker.game_fps import overlay_regions
        from yaptracker.signals import signal_regions

        return {**signal_regions(width, height), **overlay_regions(width, height)}

    def on_signals(self, frame) -> None:
        """Also while paused: the next match ends a pause (#20)."""
        if runtime.debug is not None:  # first, so a start/end sample has what was just read
            with CPU.part("debug samples"):
                runtime.debug.on_signals(frame.signals, paused=runtime.pause.paused)
        with CPU.part("match signals"):
            self.hero_select.update(frame.signals)
            self.end_screen.update(frame.signals)
            if runtime.window_size is not None:
                self.fps_meter.update(frame.signals, runtime.window_size[1])
            runtime.black.update(frame.signals.get("overview"))
        match = screen_match(runtime.matches)
        window_capture = self.found["window_capture"]
        if runtime.screen.check(window_capture, match) and runtime.watcher is not None:
            # black window: the screen it's on instead (#236); or the window, tried again (#560)
            runtime.watcher.reopen()

    # --- the black window (#217, #236, #560) -----------------------------------------------

    def overwatch_in_front(self) -> bool:
        window = runtime.watcher.window if runtime.watcher is not None else None
        if window is None or sys.platform != "win32":
            return False
        from yaptracker.capture.window import in_front

        return in_front(window)

    def window_age(self) -> float | None:
        """A starting Overwatch shows black for a while (#560)."""
        return runtime.watcher.window_age() if runtime.watcher is not None else None

    # --- the capture source ----------------------------------------------------------------

    def reopen(self) -> None:
        if runtime.watcher is not None:
            runtime.watcher.reopen()

    def open_source(self, hwnd: int):
        from yaptracker.capture.stats import CAPTURE
        from yaptracker.capture.wgc import WgcFrameSource, has_rate_setting, windows_build

        self.found["hwnd"] = hwnd
        build = windows_build()
        runtime.screen.opening()
        self.found["window_capture"] = has_rate_setting(build) and not runtime.screen.screen
        self.rate.fps = None
        if self.found["window_capture"]:
            CAPTURE.how = "WGC"  # after a stretch on the screen (#560)
            return WgcFrameSource(hwnd, self.region_for, signals_for=self.crops_for,
                                  fps=self.rate.opened())  # fmt: skip
        from yaptracker.capture.gdi import GdiFrameSource

        if runtime.screen.screen:
            log.info("capture: reading the chat box from the screen with GDI, the window was "
                     "black (#236)")  # fmt: skip
        else:
            log.info("capture: Windows build %d has no rate setting: reading the chat box with "
                     "GDI, only what's on screen (#248)", build)  # fmt: skip
        return GdiFrameSource(hwnd, self.region_for, signals_for=self.crops_for,
                              quiet=self.chat_quiet)  # fmt: skip

    def region_for(self, width: int, height: int):
        if self.found["hwnd"] is not None:
            hwnd, self.found["hwnd"] = self.found["hwnd"], None
            system_info.game_found(hwnd, width, height)
        runtime.window_size = (width, height)  # the Live view hints when this changes (#84)
        self.rate.check()  # a match started or ended: the other frame rate (#350)
        return capture_region(config.chat_region(width, height), height,
                              in_match_or_unknown(runtime.matches))  # fmt: skip

    def stall_s(self) -> float:
        return stall_limit(in_match_or_unknown(runtime.matches), self.overwatch_in_front())

    def capture_failing(self, window: int) -> None:
        """Restarts brought no picture (#506)."""
        if self.found["window_capture"]:  # GDI already: nothing else to switch to
            runtime.screen.stalled()

    def capture_ended(self, window: int, why: str) -> None:
        """What the game did (#506)."""
        focus = runtime.watcher.focus_note() if runtime.watcher else ""

        def note() -> None:  # own thread: the display lookup and files never delay the restart
            try:
                state = system_info.window_state(window)
                log.info("capture ended (%s): %s | %s", why, state, focus)
                if runtime.debug is not None:
                    runtime.debug.match_event("capture-ended", last=3)  # the last 15 s before
            except Exception as error:
                side_work.failed("noting why the capture ended", error)

        threading.Thread(target=note, name="capture ended note", daemon=True).start()

    def capture_back(self) -> None:
        if runtime.debug is not None:
            runtime.debug.match_event("capture-back")  # the first picture after (#506)

    def evening_over(self) -> None:
        """Overwatch closed: maybe for tonight (#379)."""
        self.ran_before = 0.0
        runtime.screen.game_closed()  # the next start tries the window again (#506)
        if runtime.evenings is not None and runtime.matches is not None:
            runtime.evenings.record(runtime.matches.session_id)

    def on_alive(self) -> None:
        if runtime.matches is not None:
            runtime.matches.capture_alive()

    def make_watcher(self) -> CaptureWatcher:
        common = {
            "paused": lambda: runtime.pause.paused,
            "on_alive": self.on_alive,
            "health": runtime.health,
            "on_signals": self.on_signals,
            "on_closed": self.evening_over,
        }
        if self.dev:
            runtime.window_size = (2560, 1440)  # the demo stands in for a 1440p Overwatch window
            return CaptureWatcher(lambda: 1, lambda _: demo.DemoFrameSource(), self.on_frame,
                                  **common)  # fmt: skip
        from yaptracker.capture.window import find_overwatch, in_front

        return CaptureWatcher(find_overwatch, self.open_source, self.on_frame,
                              stall_s=self.stall_s, in_front=in_front,
                              on_failing=self.capture_failing, on_ended=self.capture_ended,
                              on_back=self.capture_back, ran_before=lambda: self.ran_before,
                              **common)  # fmt: skip

    def note_a_late_start(self) -> None:
        from yaptracker.capture import process
        from yaptracker.capture.window import find_overwatch

        if find_overwatch() is not None:
            last = runtime.store.latest_session() if runtime.store else None
            started = process.started_at()
            ran = game_ran_for(started, time.time())
            if ran is not None:
                self.ran_before = ran
            runtime.health.started_late(started, last[1] if last else None)

    def start_capture(self) -> None:
        """After the store is open: gaps and matches need it."""
        if runtime.store is None:
            return  # no database (a newer one, #352): nothing to record into
        late = self.note_a_late_start if not self.dev and runtime.health is not None else None
        runtime.watcher = start_watcher(late or (lambda: None), self.make_watcher)

    def stop_capture(self) -> None:
        if runtime.watcher is not None:
            runtime.watcher.stop()

    # --- the CPU line (#302) ---------------------------------------------------------------

    def cpu_state(self) -> str:
        capturing = runtime.watcher is not None and runtime.watcher.state == "capturing"
        return cpu_state_words(capturing, runtime.pause.paused, in_match(runtime.matches))

    def _tick_cpu(self) -> None:
        while not self._ticking.wait(15.0):
            CPU.tick()

    # --- into the app ----------------------------------------------------------------------

    def install(self) -> None:
        CPU.state = self.cpu_state
        app.on_startup(lambda: threading.Thread(target=self._tick_cpu, name="cpu line",
                                                daemon=True).start())  # fmt: skip
        app.on_shutdown(self._ticking.set)
        if not self.dev and sys.platform != "win32":
            return  # native mode only exists on Windows; Linux uses --dev
        app.on_startup(self.start_capture)
        app.on_shutdown(self.stop_capture)
        if not self.dev:
            install_hotkeys()


def new_match() -> None:
    """Ctrl+Alt+M: what the Start match / End match button does (#269)."""
    if runtime.matches is not None:
        runtime.matches.toggle()


def save_chat() -> None:
    if runtime.debug is not None:
        runtime.debug.save_chat()


def lookup() -> None:
    """The window to the front; the UI focuses "Who's that?" (#27)."""
    from yaptracker.single_instance import focus_own_window

    runtime.lookup_requested = time.monotonic()
    focus_own_window()


def install_hotkeys() -> None:
    """The keys from Settings (#328), (re)registered; off while Settings listens for a new one."""
    from yaptracker.hotkeys import HotkeyListener

    actions = {"pause": runtime.pause.toggle, "new_match": new_match, "save": save_chat,
               "lookup": lookup}  # fmt: skip

    def bind_hotkeys(on: bool = True) -> None:
        if runtime.hotkeys is not None:
            runtime.hotkeys.stop()
            runtime.hotkeys = None
        if on:
            combos = config.hotkeys()
            bound = {combos[a]: f for a, f in actions.items() if combos[a]}  # (#328)
            log.info("hotkeys: %s", ", ".join(f"{a} {c}" for a, c in combos.items() if c)
                     or "none set")  # fmt: skip
            runtime.hotkeys = HotkeyListener(bound)
            runtime.hotkeys.start()

    runtime.bind_hotkeys = bind_hotkeys
    app.on_startup(bind_hotkeys)
    app.on_shutdown(lambda: bind_hotkeys(False))
