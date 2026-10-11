"""A newer YapTracker is out (#46): the calm banner in Live, What's new, and Settings -> About."""

import re
import time
from collections.abc import Callable

from nicegui import app, run, ui

from yaptracker import config, paths, runtime, updates
from yaptracker.ui.components import button, switch

HINT = "Asks GitHub which version is newest. Nothing else is sent."
HOW = "Update now closes YapTracker, updates it and starts it again. Your data stays."


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
        return f"{found.newest} is out, you have v{check.installed}."
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
                update_now_button()
                button("Close", dialog.close, "quiet")
    dialog.open()


def after_update_dialog(found: dict) -> None:
    """What's new since the version that ran before (#412). "Got it" means seen; offline (no
    notes) it says so and tries again at the next start."""
    notes = found.get("notes")
    if runtime.after_update is not None and runtime.after_update.get("to") == found.get("to"):
        runtime.after_update["shown"] = True  # opened from About: not again after the match
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-whats-new"):
        with ui.element("div").classes("yt-card-body").mark("after-update"):
            ui.label(f"What's new in v{found['to']}").classes("yt-h2")
            if notes:
                ui.label(f"Fresh paint! Here's what changed since v{found['from']}.").classes(
                    "yt-meta"
                )
                with ui.element("ul").classes("yt-release-notes"):
                    for note in notes:
                        with ui.element("li"):
                            ui.label(re.sub(r"\*\*|`", "", note))
            else:
                ui.label(
                    f"Updated to v{found['to']}. I couldn't reach GitHub for the list: I'll show "
                    "it at the next start."
                ).classes("yt-hint")
            with ui.element("div").classes("yt-row"):
                ui.element("div").classes("yt-grow")
                button("Got it", dialog.close, "primary").mark("after-update-ok")
    if notes:
        config.save_last_run_version(found["to"])  # shown: never again for this version
    dialog.open()


def watch_after_update() -> None:
    """The first start of a new version: What's new once, never in a match (#412)."""

    def look() -> None:
        found = runtime.after_update
        if found is None or found.get("shown"):
            return
        if runtime.matches is not None and runtime.matches.running:
            return  # after the match
        found["shown"] = True
        after_update_dialog(found)

    ui.timer(2.0, look)


def update_now_button() -> Callable[[], None]:
    """Update now (#46): runs the bundled update.ps1 and quits, whenever you click it (#416);
    off with the reason where it can't run. Returns its refresh."""
    b = button("Update now", lambda: go(), "primary").mark("update-now")
    said = ui.label().classes("yt-hint").mark("update-now-said")

    shown = {"state": None}

    def refresh() -> None:
        why = updates.cannot_update_now()
        if why == shown["state"]:
            return
        shown["state"] = why
        if why:
            b.props(f'disabled title="{why}"')
        else:
            b.props(remove="disabled title")

    def go() -> None:
        check = runtime.updates
        newest = check.newest if check is not None else None
        if check is not None and check.found is not None and check.found.notes:  # (#412)
            updates.save_notes(paths.data_dir() / "whats_new.json", check.installed, newest,
                               check.found.notes)  # fmt: skip
        try:
            updates.start_update(newest)
        except Exception as error:  # nothing started: YapTracker keeps running
            said.set_text(f"Couldn't start the update: {error}")
            return
        said.set_text("Updating: YapTracker closes now and is back in a minute.")
        ui.timer(1.5, quit_app, once=True)

    refresh()
    ui.timer(1.0, refresh)
    return refresh


def quit_app() -> None:
    """Like closing the window: everything shuts down cleanly (the smoke test does the same)."""
    if app.native.main_window is not None:
        app.native.main_window.destroy()


def update_banner() -> Callable[[], None]:
    """Live's banner while a newer version is out; returns its refresh. "Later" hides it until
    an even newer one shows up."""
    later = {"tag": None}
    with ui.element("div").classes("yt-banner yt-banner--calm yt-hidden").mark("update") as box:
        text = ui.label().classes("yt-grow")
        button("What's new", whats_new, "quiet").mark("update-notes")
        button("Later", lambda: hide(), "quiet").mark("update-later")
        update_now_button()

    def hide() -> None:
        later["tag"] = runtime.updates.newest if runtime.updates else None
        box.classes(add="yt-hidden")

    def refresh() -> None:
        newest = runtime.updates.newest if runtime.updates is not None else None
        if newest and newest != later["tag"]:
            text.set_text(f"YapTracker {newest} is out.")
            box.classes(remove="yt-hidden")
        else:
            box.classes(add="yt-hidden")

    return refresh


def update_section() -> None:
    """Settings -> About: what the last check found, Check now, and the daily switch."""
    status = ui.label(status_text()).classes("yt-meta").mark("update-status")
    with ui.element("div").classes("yt-row yt-wrap"):
        check_now = button("Check now", lambda: ask()).mark("update-check")
        with ui.element("div").classes("yt-row") as newer:
            button("What's new", whats_new, "quiet").mark("update-about-notes")
            update_now_button()
        this = runtime.updates and updates.notes_for(
            runtime.updates.installed, paths.data_dir() / "whats_new.json"
        )
        if this:  # what came with this version, again (#412)
            button(f"What changed in v{this['to']}", lambda: after_update_dialog(this),
                   "quiet").mark("update-this-version")  # fmt: skip
    newer.set_visibility(bool(runtime.updates and runtime.updates.newest))
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
        newer.set_visibility(bool(runtime.updates.newest))
