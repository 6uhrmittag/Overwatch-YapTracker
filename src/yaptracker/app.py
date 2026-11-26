"""Start the NiceGUI app: native window on Windows, browser mode with --dev."""

import logging
import multiprocessing
import os
import sys
import threading
from collections.abc import Callable

import numpy as np
from nicegui import app, ui
from nicegui.run import io_bound

from yaptracker import autostart as start_with_windows
from yaptracker import config, cpu_parts, demo, paths, priority, runtime, system_info
from yaptracker.capture_wiring import capture_region, start_watcher  # noqa: F401 (#311)
from yaptracker.cpu_parts import CPU
from yaptracker.ui import shell

TITLE = "YapTracker"
WINDOW_SIZE = (1280, 800)
# How long the window's page is kept when its connection drops (#562). NiceGUI's 3 s (a ping
# unanswered for 2 s drops it) is less than YapTracker sometimes has to wait for a core in a
# match: the page was thrown away and built again every few minutes, each time while waiting.
# Kept, it just catches up. Pings follow from it: every 240 s, 120 s to answer.
RECONNECT_S = 300.0
DEV_HOST = "0.0.0.0"
DEV_PORT = 8080
SMOKE_TEST_TIMEOUT_S = 90
LATER_NOTE = "unread-chat.json"  # the span of chat frames waiting to be read (#335)
AI_SPEND = "ai_spend.json"  # what the AI translations cost this month (#568)
UNREAD_DIR = "unread"  # chat frames a normal quit kept for the next start (#349)
log = logging.getLogger(__name__)


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
        # ...and in its own process, as the chat reader runs it (#563): in the exe the child is
        # this exe started again, so only the built app can prove it starts and reads there.
        if runtime.ocr_child is None:
            print("smoke test: the OCR child is off")
            return False
        # short waits here: a child that hangs must be said before the smoke test's own timeout
        runtime.ocr_child.child.waits(answer_s=40.0, read_s=20.0)
        try:
            text = " ".join(line.text for line in runtime.ocr_child.get(name).read(crop))
        except Exception as error:  # said, not waited out: CI shows why
            print(f"smoke test: {name} in its own process failed: {error!r}")
            return False
        pid = runtime.ocr_child.child.pid
        print(f"smoke test: {name} in its own process (pid {pid}) read: {text[:120]}")
        if pid is None or "WAHOO" not in text.upper():  # no pid: the main process read it
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
    """Capture runs by itself from app start: waits for Overwatch, follows it (#16). The wiring
    lives in capture_wiring (#311)."""
    from yaptracker.capture_wiring import CaptureWiring
    from yaptracker.ocr import engine as ocr

    if config.drop_ocr_gpu():
        log.warning("Use GPU for OCR was on: it's gone in v1 (#219), reading on the CPU")
    ocr.warm_up(config.ocr_engine())  # loaded in the background: nobody waits for it (#219)
    if runtime.ocr_child is not None:  # and in the reader's own process (#563)
        runtime.ocr_child.warm_up(config.ocr_engine())
    CaptureWiring(dev).install()


def debug_part(chat_read: Callable, *read) -> None:
    """The reader's debug samples count as debug samples, not reading (#302)."""
    with CPU.part("debug samples"):
        chat_read(*read)


def _open_store() -> Callable[[], None]:
    """The database opens with the app (the smoke test too: it proves SQLite + FTS5 in the exe).

    Returns the close function; run() registers it last, after capture has stopped writing.
    In named steps since #311, in the order they always ran.
    """

    def open_store() -> None:
        _open_files()
        if not _open_database():
            return  # a newer database (#352): touch nothing
        _tidy_matches()
        _start_bookkeeping()
        _start_reader()
        _start_read_again()
        _clean_up_once()

    app.on_startup(open_store)
    return _close_store


def _open_files() -> None:
    """Debug samples and line pictures: counted once in the background, then kept in bounds."""
    from yaptracker.debug import DebugSamples
    from yaptracker.lines import LinePictures

    runtime.debug = DebugSamples(paths.debug_dir(), config.debug_samples)
    runtime.debug.start()  # counted once, then 14 days / 1 GB, also after a long break
    runtime.pictures = LinePictures(paths.lines_dir(), config.line_pictures,
                                    config.picture_cap_mb() * 1_000_000)  # fmt: skip
    runtime.pictures.start()  # counted once in the background (#387), then 2 GB at most


def _open_database() -> bool:
    """The store; False when it's from a newer YapTracker: said, nothing touched (#352)."""
    from yaptracker.store.db import NewerDatabaseError
    from yaptracker.store.repo import Store

    try:
        runtime.store = Store.open()
    except NewerDatabaseError as error:  # an older build: say so, touch nothing (#352)
        log.error("%s", error)
        runtime.data_too_new = str(error)
        return False
    return True


def _tidy_matches() -> None:
    from yaptracker import later
    from yaptracker.cleanups import close_open_gaps
    from yaptracker.matches import merge_split_matches
    from yaptracker.store.backups import before_merge

    close_open_gaps(runtime.store)  # killed while paused: it overlapped every match (#463)
    try:  # one match per real match, also for matches split before (#371, #377)
        merge_split_matches(
            runtime.store,
            later.unread_matches(paths.data_dir() / UNREAD_DIR),
            lambda: before_merge(runtime.store.backup_to, paths.backup_dir()),
        )
    except Exception:
        log.exception("merging split matches failed; the matches stay as they are")


def _missed_end() -> None:
    if runtime.debug is not None:
        runtime.debug.match_event("missed-end")


def _missed_start(source: str) -> None:
    """The minutes before: was a hero select there? (#170)"""
    if runtime.debug is not None:
        runtime.debug.match_event(f"missed-start-{source}")


def _capturing() -> bool:
    return runtime.watcher is not None and runtime.watcher.state == "capturing"


def _start_bookkeeping() -> None:
    """Backups, evenings, familiar faces, matches, capture health, players, reading mode."""
    from yaptracker import later
    from yaptracker.capture.health import CaptureHealth
    from yaptracker.evenings import Evenings
    from yaptracker.familiar import FamiliarFaces
    from yaptracker.matches import MatchTracker
    from yaptracker.ocr import engine as ocr
    from yaptracker.players import PlayerMatcher
    from yaptracker.reading_mode import ReadingMode
    from yaptracker.store.backups import DailyBackup

    runtime.backups = DailyBackup(runtime.store.backup_to, paths.backup_dir(), busy=_capturing)
    runtime.backups.start()  # now (first start of the day), or once Overwatch is closed
    runtime.evenings = Evenings(paths.data_dir() / "evenings.json", runtime.store)
    try:  # the evenings since 2026-10-01 as a baseline, once (#379)
        runtime.evenings.backfill()
    except Exception:
        log.exception("filling in the evenings failed")
    runtime.familiar = FamiliarFaces(runtime.store, config.identity)
    runtime.matches = MatchTracker(runtime.store, runtime.pause, on_missed_end=_missed_end,
                                   on_missed_start=_missed_start,
                                   on_session_end=runtime.evenings.record,
                                   on_match_start=runtime.familiar.match_started)  # fmt: skip
    runtime.health = CaptureHealth(runtime.store)
    runtime.players = PlayerMatcher(
        runtime.store,
        config.identity,
        on_shaky=lambda name: runtime.debug.save_chat("new-player"),
    )
    # The chat reader's OCR in its own process (#563): a busy game can't hold up capture and the
    # window through it. Not in --dev (fake frames, and the browser reloads the app).
    get = ocr.get
    if not demo.ENABLED and config.ocr_own_process():
        from yaptracker.ocr.child import ChildEngines

        # no brakes on the child for "as fast as it can" (#652)
        runtime.ocr_child = ChildEngines(
            brakes=lambda: runtime.reader is None or not runtime.reader.no_brakes()
        )
        get = runtime.ocr_child.get
        # its CPU belongs in the "whole app" and "reading" numbers, as when OCR ran here
        cpu_parts.children = lambda: runtime.ocr_child.child.cpu_s if runtime.ocr_child else 0.0
    else:
        log.info("ocr child: off, the chat is read in the main process")
    runtime.reading = ReadingMode(
        lambda: runtime.matches,
        lambda: config.reading("competitive"),
        lambda: config.reading("other"),
        config.ocr_engine,
        get=get,
    )
    note = paths.data_dir() / LATER_NOTE
    if (lost := later.lost_span(note)) is not None:  # the app crashed or was killed (#335)
        log.warning("chat frames kept for after the match were lost: a gap record")
        runtime.store.close_gap(runtime.store.open_gap(lost[0], "deferred_lost"), lost[1])


def _start_reader() -> None:
    from yaptracker import later
    from yaptracker.reader import MIN_GAP_S, ChatReader
    from yaptracker.reading_mode import AFTER, BEST

    note = paths.data_dir() / LATER_NOTE
    kept_gap = lambda: max(runtime.reader.min_gap_s, MIN_GAP_S)  # noqa: E731 (#588)
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
        later=later.LaterFrames(kept_gap, note, unread=paths.data_dir() / UNREAD_DIR),
        keep_gap_s=kept_gap,
        read_kept=lambda image, mode: runtime.reading.read(image, runtime.ocr_scale(), mode),
        deferring=lambda: _capturing() and runtime.reading.now() == AFTER,
        idle=lambda: not _capturing() or not runtime.matches.running,
        gated=lambda: runtime.reading.chosen() != BEST,  # best live: no busy gate (#588)
        starved=lambda: runtime.watcher is not None and runtime.watcher.starved(),  # (#601)
        own_process=lambda: runtime.ocr_child is not None and runtime.ocr_child.reads_in_child(),
        lowest=runtime.ocr_child is None,  # the OCR's own process has the low priority (#563)
        doubtful=_ai_corrections(),
    )
    if (stale := runtime.reader.later.restore()) is not None:  # kept at the last quit (#349)
        runtime.store.close_gap(runtime.store.open_gap(stale[0], "deferred_lost"), stale[1])
    runtime.reader.start()
    priority.main_brakes(not runtime.reader.no_brakes())  # normal for "as fast as it can" (#652)


def _ai_corrections():
    """Doubtful lines re-read by a vision model, behind storing (#637). Never in --dev (fake
    frames, never online) and never without a key; the reader only queues."""
    from yaptracker import ai_correct, ai_translate
    from yaptracker.ocr.engine import looks_german

    if demo.ENABLED:
        return lambda message_id, ts, yap: None
    spend = runtime.ai_spend or ai_translate.Spend(paths.data_dir() / AI_SPEND)
    corrector = ai_correct.Corrector(config.openrouter_key, config.ai_cap, spend)
    labels = paths.data_dir() / "labels"
    runtime.ai_corrector = worker = ai_correct.Worker(
        corrector, runtime.store,
        lambda message_id, ts: runtime.pictures.path(message_id, ts) if runtime.pictures else None,
        relink=lambda speaker, ts: runtime.players.link(speaker, ts) if runtime.players else None,
        label=lambda entry: ai_correct.save_label(labels, entry),
        orphan=_drop_orphan,
        heard=lambda pid, match: runtime.familiar.heard(pid, match) if runtime.familiar else None,
        enabled=lambda: config.ai_correct() and bool(config.openrouter_key().strip()),
    )  # fmt: skip
    doubt = ai_correct.Doubt(runtime.store, looks_german)
    worker.start()
    return lambda message_id, ts, yap: worker.submit(message_id, ts, doubt.why(yap))


def _drop_orphan(player_id: int) -> None:
    """The player only OCR's misread name made, once the AI fixed the name (#637)."""
    if runtime.store.drop_player_if_unused(player_id) and runtime.players is not None:
        runtime.players.reload()


def _overwatch_in_front() -> bool:
    """Overwatch is the window the user looks at. By its window as last captured: between two
    captures of it (a restart, exactly when the PC is busy) the watcher has no `window`."""
    window = runtime.watcher.game_window if runtime.watcher is not None else None
    if window is None or sys.platform != "win32":
        return False
    from yaptracker.capture.window import in_front

    return in_front(window)


def _read_again_waits() -> str | None:
    """Why Read again doesn't read right now (a key of read_again.WAITS), None: it may. Not in
    a match; not while Overwatch is in front (#614: a missed match start, a custom game, busy
    menus); not while the app waited for a core in the last minute (#601)."""
    if runtime.matches is not None and runtime.matches.running:
        return "match"
    if _overwatch_in_front():
        return "front"
    if runtime.watcher is not None and runtime.watcher.starved():
        return "busy"
    return None


def _start_read_again() -> None:
    """The 'Read again, best quality' worker (#333)."""
    from yaptracker.ocr import engine as ocr
    from yaptracker.read_again import ReadAgain

    runtime.read_again = ReadAgain(
        runtime.store,
        runtime.pictures,
        lambda image: ocr.get(config.ocr_engine()).read(image, scale=runtime.ocr_scale()),
        idle=lambda: _read_again_waits() is None,
        waits=_read_again_waits,
        identity=config.identity,
        link=lambda name, ts, conf: runtime.players.link(name, ts, conf),
    )
    runtime.read_again.start()


def _clean_up_once() -> None:
    """The one-time jobs over stored data; then the players they removed are gone (#458)."""
    from yaptracker.cleanups import (
        normalise_places_once,
        remove_empty_lines_once,
        remove_input_hints_once,
    )
    from yaptracker.read_again import check_marks_once, name_icons_once

    check_marks_once(runtime.read_again, runtime.store, config.marks_checked,
                     config.save_marks_checked)  # fmt: skip
    name_icons_once(runtime.read_again, runtime.store, config.icons_named,
                    config.save_icons_named)  # fmt: skip
    remove_input_hints_once(runtime.store, paths.backup_dir(), config.hints_removed,
                            config.save_hints_removed)  # fmt: skip
    remove_empty_lines_once(runtime.store, paths.backup_dir(), config.empty_removed,
                            config.save_empty_removed)  # fmt: skip
    normalise_places_once(runtime.store, paths.backup_dir(), config.places_normalised,
                          config.save_places_normalised)  # fmt: skip
    runtime.players.reload()  # players the clean-ups removed are gone for the matcher (#458)


def _close_store() -> None:
    """In this order: nothing writes to the store after it closes. The reader stops after
    capture has: its last frame is stored first."""
    # The OCR child first (#563): a read still waiting for it ends at once and is read here, so
    # the reader's stop doesn't wait behind a child that waits for a core.
    for part in (runtime.backups, runtime.ocr_child, runtime.reader, runtime.read_again,
                 runtime.ai_corrector, runtime.health, runtime.matches):  # fmt: skip
        if part is not None:
            part.stop()
    if runtime.store is not None:
        runtime.store.close()


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


def _check_for_updates(smoke_test: bool) -> None:
    """Once a day: is a newer YapTracker out? (#46) The smoke test never goes online."""
    from yaptracker import __version__
    from yaptracker.updates import UpdateCheck

    runtime.updates = UpdateCheck(
        __version__,
        config.update_check,
        busy=lambda: runtime.matches is not None and runtime.matches.running,
        cache=paths.data_dir() / "releases.json",
        test_versions=config.test_versions,
    )
    if not smoke_test:
        app.on_startup(runtime.updates.start)
        app.on_shutdown(runtime.updates.stop)
        threading.Thread(target=_whats_new_after_update, args=(__version__,), daemon=True,
                         name="whats new").start()  # fmt: skip


def _whats_new_after_update(installed: str) -> None:
    """The first start of a new version: What's new since the one that ran before (#412). Not
    on a fresh install, nor the first start with this: no version ran before that it knows."""
    from yaptracker import updates

    last = config.last_run_version()
    found = None
    if last is not None:
        found = updates.after_update(installed, last, paths.data_dir() / "whats_new.json",
                                     paths.data_dir() / "releases.json")  # fmt: skip
    runtime.after_update = found
    if found is None:
        config.save_last_run_version(installed)


def _translator(dev: bool) -> None:
    """DeepL with the user's own key (#468), or an AI model via OpenRouter with theirs (#568);
    --dev translates with a fake, never online. Foreign lines translate themselves on their own
    thread (#469)."""
    from yaptracker import ai_translate, translate
    from yaptracker.auto_translate import AutoTranslate

    if dev:
        runtime.translator = translate.FakeTranslator()
    else:
        runtime.ai_spend = ai_translate.Spend(paths.data_dir() / AI_SPEND)  # shared (#637)
        ai = ai_translate.OpenRouter(config.openrouter_key, config.translate_to,
                                     config.ai_model, config.ai_cap, runtime.ai_spend)  # fmt: skip
        free_deepl = lambda: config.deepl_key().strip().endswith(":fx")  # noqa: E731
        runtime.translator = ai_translate.Engines(
            translate.DeepL(config.deepl_key, config.translate_to), ai, config.translate_engine,
            free_deepl)  # fmt: skip
    runtime.auto_translate = AutoTranslate(
        lambda: runtime.store,
        lambda: runtime.translator,
        lambda: config.translate_chat() and config.translate_auto(),
        config.read_languages,
        target=config.translate_to,
    )
    app.on_startup(runtime.auto_translate.start)
    app.on_shutdown(runtime.auto_translate.stop)


def run_options(dev: bool) -> dict:
    """What ui.run gets in the window and in --dev alike."""
    return {
        "title": TITLE,
        # .ico because the native window loads it with LoadImage; browsers take it too.
        "favicon": shell.STATIC_DIR / "yaptracker.ico",
        "dark": True,
        "reload": False,
        "reconnect_timeout": RECONNECT_S,  # the page survives a stall (#562)
        "show_welcome_message": dev,
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
    _check_for_updates(smoke_test)
    _translator(dev)
    app.on_shutdown(close_store)
    if smoke_test:
        _arm_smoke_test()
    common = run_options(dev)
    if dev:
        ui.run(shell.root, host=DEV_HOST, port=DEV_PORT, show=False, **common)
    else:
        app.native.window_args.update(native_window_args(background))
        if sys.platform == "win32":  # born on its saved screen, at its size (#365)
            from yaptracker import window_place

            app.native.window_args.update(window_place.birth_args())
        ui.run(shell.root, native=True, window_size=WINDOW_SIZE, **common)
