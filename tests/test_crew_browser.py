"""My names / My crew in a real browser (#168): what you type reaches config.json, also after a
restart. The other tests call the Python handlers directly; this one presses the keys.

Needs Chromium or Chrome; skipped without one. Talks to it over the DevTools protocol.
"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

websockets = pytest.importorskip("websockets")
BROWSER = next((b for b in ("chromium", "chromium-browser", "google-chrome") if shutil.which(b)),
               None)  # fmt: skip
pytestmark = pytest.mark.skipif(BROWSER is None, reason="no Chromium/Chrome installed")
SRC = Path(__file__).parents[1] / "src"
APP = """
import sys
from nicegui import ui
from yaptracker import config
from yaptracker.ui import shell
from yaptracker.ui.crew import crew_card
from yaptracker.ui.setup import setup_wizard

shell.register_static_files()

@ui.page("/settings")
def settings():
    crew_card()

@ui.page("/setup")
def setup():
    setup_wizard(lambda: None, start=3)

ui.run(port=int(sys.argv[1]), show=False, reload=False)
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while True:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(0.2)


class App:
    """The crew card and setup step 3, served from a scratch data folder."""

    def __init__(self, tmp_path: Path) -> None:
        self.data = tmp_path / "xdg"
        self.script = tmp_path / "app.py"
        self.script.write_text(APP, encoding="utf-8")
        self.port, self.proc = free_port(), None

    def start(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "NICEGUI"))}
        env.update(XDG_DATA_HOME=str(self.data), PYTHONPATH=str(SRC))  # pytest's vars: no ui.run
        self.proc = subprocess.Popen(
            [sys.executable, str(self.script), str(self.port)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        wait_for(f"http://127.0.0.1:{self.port}/settings")

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(10)

    def saved(self) -> dict:
        config = self.data / "yaptracker" / "config.json"
        return json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}


class Page:
    def __init__(self, ws) -> None:
        self.ws, self.n = ws, 0

    async def call(self, method: str, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == self.n:
                return message.get("result", {})

    async def js(self, expression: str):
        result = await self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        return result.get("result", {}).get("value")

    async def open(self, url: str) -> None:
        await self.call("Page.navigate", url=url)
        for _ in range(100):
            if await self.js("!!document.querySelector('input[aria-label]')"):
                return
            await asyncio.sleep(0.1)
        raise AssertionError(f"no name field on {url}")

    async def type_into(self, label: str, text: str) -> None:
        await self.js(f"document.querySelector('input[aria-label=\"{label}\"]').focus()")
        await self.call("Input.insertText", text=text)

    async def press_enter(self) -> None:
        for kind in ("keyDown", "keyUp"):
            text = "\r" if kind == "keyDown" else ""
            await self.call("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter",
                            windowsVirtualKeyCode=13, text=text)  # fmt: skip

    async def click(self, selector: str) -> None:
        box = await self.js(
            f"(() => {{ const e = document.querySelector({json.dumps(selector)}); "
            "e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
            "return [r.x + r.width / 2, r.y + r.height / 2] })()"
        )
        for kind in ("mousePressed", "mouseReleased"):
            await self.call("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1],
                            button="left", clickCount=1)  # fmt: skip

    async def text(self) -> str:
        return await self.js("document.body.innerText")


async def until(check, seconds: float = 10) -> None:
    deadline = time.time() + seconds
    while not check():
        if time.time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.1)


async def browse(steps) -> None:
    port = free_port()
    # No --user-data-dir: snap's Chromium can't reach pytest's /tmp folders.
    browser = subprocess.Popen(
        [BROWSER, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--remote-debugging-port={port}", "--window-size=1280,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        wait_for(f"http://127.0.0.1:{port}/json/version")
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
        url = next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"]
        async with websockets.connect(url, max_size=None) as ws:
            await steps(Page(ws))
    finally:
        browser.kill()
        browser.wait(10)


def test_names_typed_in_a_real_browser_are_saved_and_survive_a_restart(tmp_path):
    app = App(tmp_path)
    base = f"http://127.0.0.1:{app.port}"

    async def steps(page: Page) -> None:
        await page.open(f"{base}/settings")
        await page.type_into("My crew", "Void")
        await page.press_enter()
        await until(lambda: app.saved().get("crew") == ["Void"])
        await page.type_into("My crew", "Mossyfox")
        await page.click(".yt-card-head")  # typed, then clicked elsewhere
        await until(lambda: app.saved().get("crew") == ["Void", "Mossyfox"])
        await page.type_into("My crew", "Bapricot")
        await page.click(".yt-crew-list:nth-child(2) .yt-btn")  # the Add button
        await until(lambda: app.saved().get("crew") == ["Void", "Mossyfox", "Bapricot"])
        await page.open(f"{base}/setup")  # setup step 3 has the same card
        await page.type_into("My names", "Marv#2718")
        await page.click(".yt-crew-list:nth-child(1) .yt-btn")
        await until(lambda: app.saved().get("my_names") == ["Marv#2718"])

    async def after_restart(page: Page) -> None:
        await page.open(f"{base}/settings")
        text = await page.text()
        assert all(name in text for name in ("Void", "Mossyfox", "Bapricot", "Marv#2718"))

    app.start()
    try:
        asyncio.run(browse(steps))
    finally:
        app.stop()
    app.start()
    try:
        asyncio.run(browse(after_restart))
    finally:
        app.stop()
    assert app.saved()["crew"] == ["Void", "Mossyfox", "Bapricot"]  # each once, in order
