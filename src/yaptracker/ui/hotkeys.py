"""Settings -> Hotkeys (#32): every hotkey can be changed; clashes are shown, never silent.

Click Change, press the new combo. While Settings listens, YapTracker's own hotkeys are off,
so pressing the current combo doesn't pause the capture instead.
"""

import re

from nicegui import ui

from yaptracker import config, runtime
from yaptracker.hotkeys import ALTGR, check
from yaptracker.ui.components import button

ACTIONS = {
    "pause": ("Pause / resume", "Resumes by itself at the next match."),
    "lookup": ("Who's that?", "YapTracker to the front, ready to type a name."),
    "new_match": ("New match", "Only if YapTracker missed a match start."),
    "save": ("Save the last 20 s", "Keeps chat I read badly as a debug sample."),
}
_KEY = re.compile(r"^(?:Key([A-Z])|Digit([0-9])|(F[0-9]{1,2}))$")


def combo_from(code: str, ctrl: bool, alt: bool, shift: bool) -> str | None:
    """A browser key press -> "Ctrl+Alt+P"; None for keys a hotkey can't use (Shift alone...).
    Uses the key's place (code), not its character: Ctrl+Alt+Q is "@" on a German keyboard."""
    found = _KEY.match(code)
    if not found:
        return None
    mods = [name for name, on in (("Ctrl", ctrl), ("Alt", alt), ("Shift", shift)) if on]
    return "+".join([*mods, next(part for part in found.groups() if part)])


def clash(action: str, combo: str) -> str | None:
    """Why `combo` can't be the hotkey for `action`, or None."""
    problem = check(combo)
    if problem:
        return problem
    for other, taken in config.hotkeys().items():
        if other != action and taken.lower() == combo.lower():
            return f"Already used for {ACTIONS[other][0]}."
    return None


class _Keys(ui.keyboard):
    """Listens for the new combo. If Settings goes away mid-listen, the hotkeys come back."""

    on_gone = None

    def _handle_delete(self) -> None:
        if self.on_gone is not None:
            self.on_gone()
        super()._handle_delete()


def _note(combo: str, taken: list[str]) -> str | None:
    if combo in taken:
        return "Another app already has this one: pick another."
    *mods, key = combo.lower().split("+")
    if {"ctrl", "alt"} <= set(mods) and key in ALTGR:
        return f"That's also AltGr+{key.upper()} on German keyboards: no {ALTGR[key]} in chat."
    return None


def hotkeys_card() -> None:
    state: dict = {"listening": None, "problem": {}}
    with ui.element("section").classes("yt-card").mark("hotkeys"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Hotkeys").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            rows = ui.element("div").classes("yt-hotkeys")
            ui.label(
                "They work everywhere, also in Overwatch. Normal play never needs one."
                if runtime.bind_hotkeys
                else "They work in the Windows app; here you can still change them."
            ).classes("yt-hint")
    keys = _Keys(active=False, ignore=[]).mark("hotkey-keys")

    def render() -> None:
        taken = runtime.hotkeys.failed if runtime.hotkeys else []
        combos = config.hotkeys()
        rows.clear()
        with rows:
            for action, (label, hint) in ACTIONS.items():
                listening = state["listening"] == action
                with ui.element("div").classes("yt-hotkey").mark(f"hotkey-{action}"):
                    with ui.element("div").classes("yt-grow"):
                        ui.label(label).classes("yt-hotkey-name")
                        ui.label(hint).classes("yt-meta")
                    combo = combos[action]
                    note = state["problem"].get(action) or _note(combo, taken)
                    if note:
                        ui.label(note).classes("yt-hotkey-note").mark(f"hotkey-note-{action}")
                    ui.label("Press the new keys\u2026" if listening else combo.replace("+", " ")
                             ).classes("yt-keycap yt-keycap--big")  # fmt: skip
                    if listening:
                        button("Cancel", lambda: stop(), "quiet").mark("hotkey-cancel")
                    else:
                        button("Change", lambda a=action: listen(a), "quiet").mark(
                            f"hotkey-change-{action}"
                        )

    def listen(action: str) -> None:
        state["listening"] = action
        state["problem"].pop(action, None)
        keys.active = True
        if runtime.bind_hotkeys:
            runtime.bind_hotkeys(False)  # so the current combo reaches this page
        render()

    def stop() -> None:
        state["listening"] = None
        keys.active = False
        if runtime.bind_hotkeys:
            runtime.bind_hotkeys(True)
        render()

    def on_key(e) -> None:
        action = state["listening"]
        if action is None or not e.action.keydown:
            return
        if e.key.code == "Escape":
            stop()
            return
        combo = combo_from(e.key.code, e.modifiers.ctrl, e.modifiers.alt, e.modifiers.shift)
        if combo is None:
            return  # a modifier on its own: wait for the rest
        problem = clash(action, combo)
        if problem:
            state["problem"][action] = f"{combo.replace('+', ' ')}: {problem}"
        else:
            config.save_hotkey(action, combo)
            state["problem"].pop(action, None)
        stop()

    def gone() -> None:
        if state["listening"] is not None and runtime.bind_hotkeys:
            runtime.bind_hotkeys(True)

    keys.on_key(on_key)
    keys.on_gone = gone
    render()
