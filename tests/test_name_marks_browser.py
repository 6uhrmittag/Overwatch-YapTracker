"""Name marks keep the line height (#519): the real Live page in a real browser; a known
player's line and a stranger's line with the same text are exactly as high, system lines too.

Needs Chromium or Chrome (skipped without one), like test_crew_browser.py, whose helpers it uses.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from tests.test_crew_browser import SRC, Page, browse, free_port, pytestmark, wait_for  # noqa: F401

APP = """
import sys
from pathlib import Path
from nicegui import ui
from yaptracker import config, runtime
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell

shell.register_static_files()
folder = Path(sys.argv[2])
store = Store.open(folder / "yaptracker.db", folder / "backups")
config.save_setup_state("done")
session = store.start_session(1.0)
old = store.start_match(session, 10.0, "heroselect")
ids = {}
for name, verdict in (("NoodleBonk", "friend"), ("Pebble", None), ("Kettle", None)):
    ids[name] = store.add_player(name, 10.0)
    if name != "Kettle":
        store.add_message(ts=11.0, channel="match", text="hi", match_id=old, speaker_raw=name,
                          player_id=ids[name])
    if verdict:
        store.set_verdict(ids[name], verdict)
tracker = MatchTracker(store, Pause())
tracker.new_match(100.0, "heroselect")
LINES = [("match", "NoodleBonk", "gg go next"), ("match", "Kettle", "gg go next"),
         ("team", "Pebble", "gg go next"),
         ("system", "NoodleBonk", "[NoodleBonk] started playing Overwatch."),
         ("system", "Kettle", "[Kettle] started playing Overwatch.")]
for n, (channel, name, text) in enumerate(LINES):
    store.add_message(ts=101.0 + n, channel=channel, text=text, match_id=tracker.match_id,
                      speaker_raw=name, player_id=ids[name] if channel != "system" else None)
runtime.store, runtime.matches = store, tracker

ui.run(shell.root, port=int(sys.argv[1]), show=False, reload=False)
"""

HEIGHTS = """[...document.querySelectorAll('.yt-line')].map(l => [l.offsetHeight,
    l.querySelectorAll('.yt-mark').length])"""


def test_a_mark_doesnt_change_the_line_height(tmp_path: Path):
    script, port = tmp_path / "app.py", free_port()
    script.write_text(APP, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "NICEGUI"))}
    env.update(XDG_DATA_HOME=str(tmp_path / "xdg"), PYTHONPATH=str(SRC))
    proc = subprocess.Popen([sys.executable, str(script), str(port), str(tmp_path)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    base = f"http://127.0.0.1:{port}"
    seen = {}

    async def steps(page: Page) -> None:
        for width in (1280, 720):
            await page.call("Emulation.setDeviceMetricsOverride", width=width, height=900,
                            deviceScaleFactor=1, mobile=False)  # fmt: skip
            await page.call("Page.navigate", url=base)
            await asyncio.sleep(1)
            await page.until_js("document.querySelectorAll('.yt-line').length === 5", 20)
            await asyncio.sleep(0.5)
            seen[width] = await page.js(HEIGHTS)

    try:
        wait_for(base)
        asyncio.run(browse(steps, tmp_path))
    finally:
        proc.terminate()
        proc.wait(10)
    for width, lines in seen.items():
        marks = [n for _, n in lines]
        assert marks == [1, 0, 1, 1, 0], (width, lines)  # Bestie, stranger, met, system x2
        heights = [h for h, _ in lines]
        assert heights[0] == heights[1] == heights[2], (width, lines)
        assert heights[3] == heights[4], (width, lines)
