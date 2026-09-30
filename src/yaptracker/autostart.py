"""Start with Windows (#45): a per-user Run entry. No admin rights, no service, no tray icon.

The registry entry is what Windows uses, so it is the truth. config.json only remembers the
user's choice, so the default (on) is applied once and never overrides a later "off".
"""

import contextlib
import sys

from yaptracker import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "YapTracker"
BACKGROUND = "--background"


def supported() -> bool:
    """Only the installed exe can start itself; `python -m yaptracker` can't."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def command() -> str:
    return f'"{sys.executable}" {BACKGROUND}'


def read(name: str = NAME) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def write(value: str | None, name: str = NAME) -> None:
    """Set the entry, or remove it with None."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if value is None:
            with contextlib.suppress(FileNotFoundError):  # already gone is fine
                winreg.DeleteValue(key, name)
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def enabled() -> bool:
    return supported() and read() is not None


def set_enabled(on: bool) -> None:
    config.save_autostart(on)
    write(command() if on else None)


def apply_at_start(choice_from_installer: bool | None = None) -> None:
    """On every start: default on the first time, and re-point the entry at this exe.

    After an update or a move the exe path may differ; writing it again keeps it right.
    `choice_from_installer` is update.ps1's one-time question (--autostart on|off).
    """
    if not supported():
        return
    if choice_from_installer is not None:
        config.save_autostart(choice_from_installer)
    choice = config.autostart()
    if choice is None:  # first start of the installed app: on by default
        choice = True
        config.save_autostart(True)
    write(command() if choice else None)
