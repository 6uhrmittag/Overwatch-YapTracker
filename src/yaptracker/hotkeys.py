"""Global hotkeys via RegisterHotKey (#20). Windows only.

Only listens: YapTracker never sends keystrokes or clicks anywhere, least of all to the game.
"""

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

_MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
_NOREPEAT = 0x4000
_WM_HOTKEY, _WM_QUIT = 0x0312, 0x0012


def parse(combo: str) -> tuple[int, int]:
    """'Ctrl+Alt+P' -> (modifiers, virtual key). Letters, digits and F1-F24."""
    *mods, key = [part.strip().lower() for part in combo.split("+")]
    modifiers = _NOREPEAT
    for mod in mods:
        modifiers |= _MODIFIERS[mod]
    if len(key) == 1 and key.isalnum():
        return modifiers, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    raise ValueError(f"unsupported key in hotkey {combo!r}")


# Ctrl+Alt is AltGr on German keyboards: these would also eat a character you type in chat.
ALTGR = {"q": "@", "e": "\u20ac", "7": "{", "8": "[", "9": "]", "0": "}"}


def check(combo: str) -> str | None:
    """Why this combo can't be a global hotkey, or None if it can."""
    try:
        parse(combo)
    except (KeyError, ValueError):
        return "Letters, digits or F1-F24, with Ctrl and/or Alt."
    mods = {part.strip().lower() for part in combo.split("+")[:-1]}
    if not mods & {"ctrl", "alt"} and not combo.split("+")[-1].strip().lower().startswith("f"):
        return "Needs Ctrl or Alt, or you couldn't type that key anywhere else."
    return None


class HotkeyListener:
    """Calls the callback on its own thread whenever the combo is pressed anywhere in Windows."""

    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        self._bindings = [(combo, f) for combo, f in bindings.items() if combo]  # "" = not set
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self.failed: list[str] = []  # combos another app already owns; Settings shows them (#32)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self) -> None:
        """Unregisters everything before it returns, so a new listener can take the same keys."""
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(5)

    def _run(self) -> None:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        for i, (combo, _) in enumerate(self._bindings):
            if not user32.RegisterHotKey(None, i + 1, *parse(combo)):
                log.warning("hotkey %s is taken by another app", combo)
                self.failed.append(combo)
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_HOTKEY and 1 <= msg.wParam <= len(self._bindings):
                combo, callback = self._bindings[msg.wParam - 1]
                try:
                    callback()
                except Exception:  # one broken action must not kill every hotkey
                    log.exception("hotkey %s failed", combo)
        for i in range(len(self._bindings)):
            user32.UnregisterHotKey(None, i + 1)
