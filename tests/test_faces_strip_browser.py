"""Look who's back! never moves the chat (#518): the real Live page in a real browser, with 0, 1,
3 and 6 familiar faces, wide and narrow; the chat card's top stays where it was.

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
from nicegui import app, ui
from yaptracker import config, runtime
from yaptracker.familiar import FamiliarFaces
from yaptracker.store.repo import Store
from yaptracker.ui import shell

shell.register_static_files()  # theme.css: the layout under test
folder = Path(sys.argv[2])
store = Store.open(folder / "yaptracker.db", folder / "backups")
config.save_setup_state("done")
runtime.store, runtime.familiar = store, FamiliarFaces(store)
session = store.start_session(1.0)
now = store.start_match(session, 100.0, "heroselect")
NAMES = ["NoodleBonk", "gremlin.exe", "Pebble", "Kettle", "Mothball", "Sprocket"]
NOTES = ["Hype Lucio, calls every flank and never stops talking about it", "", "", "", "", ""]

@app.get("/add/{n}")
def add(n: int):
    name = NAMES[n]
    pid = store.add_player(name, 1.0)
    old = store.start_match(session, 10.0 + n, "gap")
    store.add_message(ts=10.0 + n, channel="match", text="gg", match_id=old, speaker_raw=name,
                      player_id=pid)
    store.set_verdict(pid, ["friend", "avoid", "fun", None, "neutral", "friend"][n])
    store.set_notes(pid, NOTES[n])
    runtime.familiar.heard(pid, now)
    return len(runtime.familiar.active())

@app.get("/next")
def next_match():
    runtime.familiar.match_started(store.start_match(session, 200.0, "heroselect"))

ui.run(shell.root, port=int(sys.argv[1]), show=False, reload=False)
"""

# where layout puts it (offsetTop up the chain): the cards' pop-in transform doesn't count
TOP = """(() => { let e = document.querySelector('.yt-card--chat'), y = 0;
  while (e) { y += e.offsetTop; e = e.offsetParent; } return y; })()"""


def test_the_chat_stays_put_with_0_1_3_and_6_faces_wide_and_narrow(tmp_path: Path):
    script, port = tmp_path / "app.py", free_port()
    script.write_text(APP, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "NICEGUI"))}
    env.update(XDG_DATA_HOME=str(tmp_path / "xdg"), PYTHONPATH=str(SRC))
    proc = subprocess.Popen([sys.executable, str(script), str(port), str(tmp_path)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    base = f"http://127.0.0.1:{port}"
    tops: dict[int, list[int]] = {1280: [], 720: []}

    async def faces(page: Page, n: int) -> None:
        await page.until_js(f"document.querySelectorAll('.yt-face-chip').length >= {min(n, 4)}")
        await asyncio.sleep(0.6)  # the chip's slide-in is over

    async def steps(page: Page) -> None:
        for width in tops:
            await page.call("Emulation.setDeviceMetricsOverride", width=width, height=900,
                            deviceScaleFactor=1, mobile=False)  # fmt: skip
            await page.call("Page.navigate", url=base)
            await asyncio.sleep(1)  # the old page's context is gone
            if width == 1280:
                await page.until_js("!!document.querySelector('.yt-strip .yt-strip-empty')", 20)
                tops[width].append(await page.js(TOP))
                for n in range(6):
                    await page.js(f"fetch('/add/{n}')")
                    if n + 1 in (1, 3, 6):
                        await faces(page, n + 1)
                        tops[width].append(await page.js(TOP))
            else:  # the same six faces, narrow: name + sticker only; then gone at the next match
                await faces(page, 6)
                tops[width].append(await page.js(TOP))
                assert (
                    await page.js(
                        "getComputedStyle(document.querySelector('.yt-face-chip-meta')).display"
                    )
                    == "none"
                )
                await page.js("fetch('/next')")
                await page.until_js("!!document.querySelector('.yt-strip .yt-strip-empty')")
                tops[width].append(await page.js(TOP))

    try:
        wait_for(base)
        asyncio.run(browse(steps, tmp_path))
    finally:
        proc.terminate()
        proc.wait(10)
    assert len(tops[1280]) == 4 and len(set(tops[1280])) == 1, tops
    assert len(tops[720]) == 2 and len(set(tops[720])) == 1, tops
