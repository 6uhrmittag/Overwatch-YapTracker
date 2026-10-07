"""Settings -> Hotkeys (#32): every hotkey can be changed; clashes are shown, never silent.

Click Change, press the new combo. While Settings listens, YapTracker's own hotkeys are off,
so pressing the current combo doesn't pause the capture instead.
"""

import contextlib
import re

from nicegui import background_tasks, ui

from yaptracker import config, runtime
from yaptracker.hotkeys import ALTGR, check
from yaptracker.ui.components import button

ACTIONS = {
    "pause": ("Pause / resume", "Resumes by itself at the next match."),
    "lookup": ("Who's that?", "YapTracker to the front, ready to type a name."),
    "new_match": (
        "Start / end match",
        "Only if YapTracker missed a hero select or a result screen.",
    ),
    "save": ("Save the last 20 s", "Keeps chat I read badly as a debug sample."),
}
_KEY = re.compile(r"^(?:Key([A-Z])|Digit([0-9])|(F[0-9]{1,2}))$")
# The browser's map of where keys are to what they type on the user's layout (#245), e.g.
# {"KeyL": "n"} on Dvorak, {"KeyY": "z"} on QWERTZ. Chromium and WebView2 have it.
LAYOUT_JS = ("navigator.keyboard && navigator.keyboard.getLayoutMap ? "
             "navigator.keyboard.getLayoutMap().then(m => Object.fromEntries(m)) : {}")  # fmt: skip
NO_UMLAUTS = "Ä, Ö, Ü and ß can't be hotkeys: pick A-Z, a digit or F1-F24."


def combo_from(code: str, ctrl: bool, alt: bool, shift: bool,
               layout: dict[str, str] | None = None) -> str | None:  # fmt: skip
    """A browser key press -> "Ctrl+Alt+P"; None for keys a hotkey can't use (Shift alone...).

    One rule (#245): the letter the key types on the user's layout, from `layout` (the browser's
    layout map). Not the key's character in this press: with Ctrl+Alt (AltGr on a German
    keyboard) Q types "@". Not the key's place either: on Dvorak the key at QWERTY's L types n.
    Windows registers the letter's virtual key, which it maps through the same layout, so what
    you press is what's saved, shown and fired. Without a layout map: the QWERTY place."""
    found = _KEY.match(code)
    typed = (layout or {}).get(code, "")
    if len(typed) == 1 and typed.isalpha() and not typed.isascii():
        raise ValueError(NO_UMLAUTS)  # ä ö ü ß: there's no virtual key for them
    if found and found.group(3):
        key = found.group(3)  # F1-F24 are the same everywhere
    elif len(typed) == 1 and typed.isascii() and typed.isalnum():
        key = typed.upper()
    elif found and not typed:  # no layout map for this key: its QWERTY place
        key = found.group(1) or found.group(2)
    else:
        return None  # a key that types no letter or digit here ("'" on Dvorak)
    mods = [name for name, on in (("Ctrl", ctrl), ("Alt", alt), ("Shift", shift)) if on]
    return "+".join([*mods, key])


def clash(action: str, combo: str) -> str | None:
    """Why `combo` can't be the hotkey for `action`, or None."""
    problem = check(combo)
    if problem:
        return problem
    for other, taken in config.hotkeys().items():
        if other != action and taken and taken.lower() == combo.lower():
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
    if not combo:
        return None
    if combo in taken:
        return "Another app already has this one: pick another."
    *mods, key = combo.lower().split("+")
    if {"ctrl", "alt"} <= set(mods) and key in ALTGR:
        return f"That's also AltGr+{key.upper()} on German keyboards: no {ALTGR[key]} in chat."
    return None


def _row(action: str, combo: str, note: str | None, listening: bool, do: dict) -> None:
    """One action: its name and hint, the combo or "Not set", Change and Clear (#328)."""
    label, hint = ACTIONS[action]
    with ui.element("div").classes("yt-hotkey").mark(f"hotkey-{action}"):
        with ui.element("div").classes("yt-grow"):
            ui.label(label).classes("yt-hotkey-name")
            ui.label(hint).classes("yt-meta")
        if note:
            ui.label(note).classes("yt-hotkey-note").mark(f"hotkey-note-{action}")
        if listening:
            ui.label("Press the new keys\u2026").classes("yt-keycap yt-keycap--big")
            button("Cancel", lambda: do["cancel"](), "quiet").mark("hotkey-cancel")
            return
        if combo:
            ui.label(combo.replace("+", " ")).classes("yt-keycap yt-keycap--big")
        else:
            ui.label("Not set").classes("yt-meta").mark(f"hotkey-unset-{action}")
        button("Change", lambda: do["change"](action), "quiet").mark(f"hotkey-change-{action}")
        if combo:
            button("Clear", lambda: do["clear"](action), "quiet").mark(f"hotkey-clear-{action}")


def hotkeys_card() -> None:
    state: dict = {"listening": None, "problem": {}}
    with ui.element("section").classes("yt-card").mark("hotkeys"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Hotkeys").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            rows = ui.element("div").classes("yt-hotkeys")
            ui.label(
                "Optional. Everything works without hotkeys; set one if you want an action "
                "without switching windows. They work everywhere, also in Overwatch."
                if runtime.bind_hotkeys
                else "Optional. They work in the Windows app; here you can still set them."
            ).classes("yt-hint")
    keys = _Keys(active=False, ignore=[]).mark("hotkey-keys")

    def render() -> None:
        taken = runtime.hotkeys.failed if runtime.hotkeys else []
        combos = config.hotkeys()
        rows.clear()
        with rows:
            for action in ACTIONS:
                note = state["problem"].get(action) or _note(combos[action], taken)
                _row(action, combos[action], note, state["listening"] == action,
                     {"change": listen, "clear": clear, "cancel": stop})  # fmt: skip

    async def learn_layout() -> None:
        """Which letters this keyboard types (#245); asked once per page."""
        with contextlib.suppress(Exception):  # an old browser, or no answer: the QWERTY places
            state["layout"] = await ui.run_javascript(LAYOUT_JS, timeout=2) or {}

    def listen(action: str) -> None:
        state["listening"] = action
        state["problem"].pop(action, None)
        keys.active = True
        if runtime.bind_hotkeys:
            runtime.bind_hotkeys(False)  # so the current combo reaches this page
        render()
        if "layout" not in state:
            state["layout"] = {}
            background_tasks.create(learn_layout(), name="keyboard layout")

    def clear(action: str) -> None:
        """Unbinds it at once (#328): no confirmation, the row says "Not set" again."""
        config.save_hotkey(action, "")
        state["problem"].pop(action, None)
        if runtime.bind_hotkeys:
            runtime.bind_hotkeys(True)  # registered again without it
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
        try:
            combo = combo_from(e.key.code, e.modifiers.ctrl, e.modifiers.alt, e.modifiers.shift,
                               state.get("layout"))  # fmt: skip
        except ValueError as umlaut:
            state["problem"][action] = str(umlaut)
            stop()
            return
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
