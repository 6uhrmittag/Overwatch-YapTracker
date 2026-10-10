"""A newer YapTracker is out (#46): the calm banner in Live, What's new, and Settings -> About."""

import re
import time
from collections.abc import Callable

from nicegui import run, ui

from yaptracker import config, runtime
from yaptracker.ui.components import button, switch

HINT = "Asks GitHub which version is newest. Nothing else is sent."
HOW = "tools\\update.ps1 gets it, your data stays where it is."


def status_text() -> str:
    """One line for About: never checked, up to date, newer, or the check failed."""
    check = runtime.updates
    found = check.found if check is not None else None
    if found is None:
        on = check is not None and config.update_check()
        return "I look for a newer version once a day." if on else "The daily look is off."
    at = time.localtime(found.at)
    when = time.strftime("%H:%M" if at[:3] == time.localtime()[:3] else "%a %H:%M", at)
    if found.error:
        return f"Couldn't reach GitHub at {when} (offline?). I'll try again in a day."
    if found.newest:
        return f"{found.newest} is out, you have v{check.installed}. {HOW}"
    return f"Up to date (v{check.installed}), checked at {when}."


def whats_new() -> None:
    """The release notes since the installed version, in a dialog."""
    check = runtime.updates
    if check is None or check.found is None or not check.found.newest:
        return
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-whats-new"):
        with ui.element("div").classes("yt-card-body"):
            ui.label(f"What's new in {check.found.newest}").classes("yt-h2")
            ui.label(f"Since your v{check.installed}, newest first.").classes("yt-meta")
            with ui.element("ul").classes("yt-release-notes").mark("whats-new"):
                for note in check.found.notes:
                    with ui.element("li"):
                        ui.label(re.sub(r"\*\*|`", "", note))
            with ui.element("div").classes("yt-row"):
                ui.label(HOW).classes("yt-hint yt-grow")
                button("Close", dialog.close, "quiet")
    dialog.open()


def update_banner() -> Callable[[], None]:
    """Live's banner while a newer version is out; returns its refresh. "Later" hides it until
    an even newer one shows up."""
    later = {"tag": None}
    with ui.element("div").classes("yt-banner yt-banner--calm yt-hidden").mark("update") as box:
        text = ui.label().classes("yt-grow")
        button("What's new", whats_new, "quiet").mark("update-notes")
        button("Later", lambda: hide(), "quiet").mark("update-later")

    def hide() -> None:
        later["tag"] = runtime.updates.newest if runtime.updates else None
        box.classes(add="yt-hidden")

    def refresh() -> None:
        newest = runtime.updates.newest if runtime.updates is not None else None
        if newest and newest != later["tag"]:
            text.set_text(f"YapTracker {newest} is out. {HOW}")
            box.classes(remove="yt-hidden")
        else:
            box.classes(add="yt-hidden")

    return refresh


def update_section() -> None:
    """Settings -> About: what the last check found, Check now, and the daily switch."""
    status = ui.label(status_text()).classes("yt-meta").mark("update-status")
    with ui.element("div").classes("yt-row"):
        check_now = button("Check now", lambda: ask()).mark("update-check")
        notes = button("What's new", whats_new, "quiet").mark("update-about-notes")
    notes.set_visibility(bool(runtime.updates and runtime.updates.newest))
    switch("Check for updates once a day", config.update_check(), config.save_update_check).mark(
        "update-switch"
    )
    ui.label(HINT).classes("yt-hint")

    async def ask() -> None:
        if runtime.updates is None:
            return
        check_now.props("loading")
        await run.io_bound(runtime.updates.check)
        check_now.props(remove="loading")
        status.set_text(status_text())
        notes.set_visibility(bool(runtime.updates.newest))
