import sys

import pytest

from yaptracker import autostart, config


@pytest.fixture
def registry(monkeypatch):
    """Pretend to be the installed exe on Windows, with an in-memory Run key."""
    values: dict[str, str] = {}
    monkeypatch.setattr(autostart, "supported", lambda: True)
    monkeypatch.setattr(
        sys, "executable", r"C:\Users\me\AppData\Local\YapTracker\app\YapTracker.exe"
    )
    monkeypatch.setattr(autostart, "read", lambda name=autostart.NAME: values.get(name))

    def write(value, name=autostart.NAME):
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value

    monkeypatch.setattr(autostart, "write", write)
    return values


def test_first_start_turns_it_on_and_points_at_this_exe(registry):
    autostart.apply_at_start()
    assert registry["YapTracker"] == (
        r'"C:\Users\me\AppData\Local\YapTracker\app\YapTracker.exe" --background'
    )
    assert config.autostart() is True


def test_off_stays_off_on_later_starts(registry):
    autostart.apply_at_start()
    autostart.set_enabled(False)
    autostart.apply_at_start()
    assert "YapTracker" not in registry and not autostart.enabled()


def test_installer_answer_no_means_no_entry(registry):
    autostart.apply_at_start(choice_from_installer=False)
    assert "YapTracker" not in registry and config.autostart() is False


def test_entry_follows_the_exe_after_a_move(registry, monkeypatch):
    autostart.apply_at_start()
    monkeypatch.setattr(sys, "executable", r"D:\Games\YapTracker\YapTracker.exe")
    autostart.apply_at_start()
    assert registry["YapTracker"] == r'"D:\Games\YapTracker\YapTracker.exe" --background'


def test_nothing_happens_outside_the_installed_app(monkeypatch):
    monkeypatch.setattr(autostart, "supported", lambda: False)
    monkeypatch.setattr(autostart, "write", lambda *a, **k: pytest.fail("must not write"))
    autostart.apply_at_start()
    assert config.autostart() is None
