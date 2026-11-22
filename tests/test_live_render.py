"""#562: Live renders took 2-52 s on Marv's PC. Not the database (a render is ~50 ms on his):
the app waited for a core in a match, lost its page and built it again, waiting. So the page is
kept across stalls, the log line tells working from waiting, and these keep a render cheap on a
database far bigger than a real one."""

import logging
import random
import re
import threading
import time

import pytest
from nicegui.testing import user_simulation

from yaptracker import app, config, runtime
from yaptracker.familiar import FamiliarFaces
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell, timing

NOW, DAY = 1_795_000_000.0, 86400.0
MATCHES, LINES, PLAYERS = 1000, 100_000, 5000  # Marv's after 2 months: 357, 10 135, 1 068


@pytest.fixture(scope="module")
def big_db(tmp_path_factory):
    """Ten times Marv's: 100 lines a match, every speaker a known player with a verdict."""
    folder = tmp_path_factory.mktemp("big")
    store = Store.open(folder / "yaptracker.db", folder / "backups")
    random.seed(562)
    conn = store._conn
    conn.execute("BEGIN")
    conn.execute("INSERT INTO sessions (started_at) VALUES (?)", (NOW - 700 * DAY,))
    conn.executemany(
        "INSERT INTO matches (session_id, started_at, ended_at, source) VALUES (1, ?, ?, 'gap')",
        [(NOW - (MATCHES - n) * 600, NOW - (MATCHES - n) * 600 + 500) for n in range(MATCHES)],
    )
    conn.executemany(
        "INSERT INTO players (display_name, verdict, notes, first_seen, last_seen) "
        "VALUES (?, ?, 'nice', ?, ?)",
        [(f"Player{n}", random.choice(["friend", "fun", "neutral", "avoid", None]),
          NOW - 600 * DAY, NOW - DAY) for n in range(PLAYERS)],
    )  # fmt: skip
    rows = []
    for n in range(LINES):
        match, player = n % MATCHES + 1, random.randrange(PLAYERS) + 1
        rows.append((match, NOW - (MATCHES - match + 1) * 600 + n // MATCHES,
                     random.choice(["team", "match"]), f"Player{player - 1}", player,
                     "group up and push the cart pls"))  # fmt: skip
    conn.executemany(
        "INSERT INTO chat_messages (match_id, ts, channel, speaker_raw, player_id, text) "
        "VALUES (?, ?, ?, ?, ?, ?)", rows)  # fmt: skip
    conn.execute("COMMIT")
    yield store
    store.close()


@pytest.fixture
def live(big_db, monkeypatch):
    """Live on the newest match of the big database."""
    config.save_setup_state("done")
    tracker = MatchTracker(big_db, Pause())
    tracker.match_id, tracker.match_started_at = MATCHES, NOW - 600
    faces = FamiliarFaces(big_db, config.identity)
    faces.match_started(MATCHES)
    monkeypatch.setattr(runtime, "store", big_db)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "familiar", faces)
    return big_db


class Ticker:
    """A thread that wants to run every 50 ms, like the capture watchdog: its longest wait."""

    def __init__(self) -> None:
        self.longest, self._stop = 0.0, threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        last = time.perf_counter()
        while not self._stop.wait(0.05):
            now = time.perf_counter()
            self.longest, last = max(self.longest, now - last), now

    def __enter__(self) -> "Ticker":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()


async def render(times: int) -> list[float]:
    took = []
    for _ in range(times):
        async with user_simulation(root=shell.root) as user:
            started = time.perf_counter()
            await user.open("/")
            await user.should_see("100 yaps")
            took.append(time.perf_counter() - started)
    return took


async def test_live_stays_quick_on_a_huge_database_and_lets_other_threads_run(live):
    """Only what the render itself does: the GIL it holds. Not Windows giving the game the
    cores, which no test here can show."""
    await render(1)  # imports and caches
    with Ticker() as ticker:
        took = await render(5)
    # Here ~0.2 s each, page load included (the issue's bar: 0.5 s median, 2 s max). CI runs
    # this beside other workers with coverage on, so only the outer bar is held there.
    assert max(took) < 2.0, took
    assert ticker.longest < 1.0, ticker.longest  # the watchdog's tick is never a second late


SMALL = {"players", "player_aliases"}  # walked whole for the verdict marks (#519): a few 1000


async def test_live_never_walks_the_chat_or_the_matches(live):
    """Every query of a Live render, as SQLite plans it: the tables that grow with every evening
    are only reached by an index."""
    asked: list[str] = []
    await render(1)
    live._conn.set_trace_callback(asked.append)
    try:
        await render(1)
    finally:
        live._conn.set_trace_callback(None)
    reads = sorted({sql for sql in asked if sql.lstrip().upper().startswith(("SELECT", "WITH"))})
    assert any("live_messages" in sql or "chat_messages" in sql for sql in reads), reads
    for sql in reads:
        plan = " | ".join(row[3] for row in live._conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
        walked = set(re.findall(r"SCAN (\w+)(?! USING)", plan))  # aliases too ("matches m")
        assert walked <= SMALL, (sql, plan)


def test_a_very_slow_render_tells_working_from_waiting_and_names_its_top_three():
    # [on the clock, CPU]: the waiting landed on the layout, the work was the chat lines
    parts = {"layout": [40000.0, 60.0], "chat lines": [9000.0, 120.0],
             "familiar faces": [900.0, 5.0], "status": [2000.0, 30.0]}  # fmt: skip
    said = timing.line("live", 51913.0, 240.0, parts)
    assert said == ("ui: live took 51913 ms, 240 ms of it working "
                    "(chat lines 120, layout 60, status 30)")  # fmt: skip
    parts = {"stats": [12.0, 10.0], "pictures": [380.0, 20.0]}
    assert timing.line("settings", 420.0, 400.0, parts) == (
        "ui: settings took 420 ms (stats 12, pictures 380)"
    )
    assert timing.line("search", 200.0, 190.0, {}) == "ui: search took 200 ms"


async def test_a_live_render_logs_its_parts(live, monkeypatch, caplog):
    monkeypatch.setattr(timing, "SLOW_MS", 0)
    monkeypatch.setattr(timing, "VERY_SLOW_MS", 0)
    with caplog.at_level(logging.INFO):
        await render(1)
    (said,) = [r.getMessage() for r in caplog.records if "ui: live took" in r.getMessage()]
    assert "ms of it working (" in said
    named = said[said.index("(") + 1 : -1]
    assert len(named.split(", ")) == 3 and "chat lines" in named, said
    assert timing._lap_at is None  # the timer's refreshes measure nothing


async def test_page_loads_are_counted_in_the_log(live, caplog):
    with caplog.at_level(logging.INFO, logger="yaptracker.ui.shell"):
        await render(2)
    loads = [r.getMessage() for r in caplog.records if "ui: page loaded" in r.getMessage()]
    first, second = (int(said.split("(")[1].split()[0]) for said in loads)
    assert second == first + 1


def test_the_page_survives_the_stalls_seen_in_matches():
    """NiceGUI's pings follow from the reconnect window (nicegui.py: 0.4 of it to answer). The
    longest stall in Marv's logs was 30 s."""
    assert app.RECONNECT_S * 0.4 >= 60
    for dev in (False, True):
        assert app.run_options(dev)["reconnect_timeout"] == app.RECONNECT_S


async def test_a_replaced_page_goes_when_the_new_one_connects(live):
    """Kept for minutes, a page the window no longer shows would run its timers that long."""
    async with user_simulation(root=shell.root) as user:
        await user.open("/")
        old = user.client
        assert old.yt_connected and not old.is_deleted
        old.tab_id = None  # its window is gone (a reload)
        await user.open("/")
        assert old.is_deleted and not user.client.is_deleted
