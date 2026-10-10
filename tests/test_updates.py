"""A newer YapTracker is out (#46): the daily check, What's new, the banner and About."""

import asyncio
import logging
import urllib.error
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.ui import shell
from yaptracker.updates import DAY_S, NOTES_CAP, UpdateCheck, candidates, version, whats_new


def release(tag, *bullets, prerelease=True, draft=False):
    body = "### What's new\n" + "".join(f"- {b}\n" for b in bullets) + "\nUpdate: run it."
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "body": body}


RELEASES = [  # as GitHub lists them, newest first
    release("v0.5.412", "Grímsvötn is now **recognized**.", "Behind the scenes: a test."),
    release(
        "v0.5.410", "A quiet chat no longer splits a match.", "Grímsvötn is now **recognized**."
    ),
    release("v0.5.405", "Old news."),
    release("v0.5.399", "Older news."),
]


def test_versions_compare_as_numbers():
    assert version("v0.5.399") < version("v0.5.412") < version("v1.0.0")
    assert version("0.5.412") == (0, 5, 412) and version("0.0.0.dev0") == (0, 0, 0)
    assert version("nightly") is None


def test_pre_releases_count_on_v0_only():
    on_v1 = [release("v1.1.0", prerelease=False), release("v1.0.9"), release("v1.2.0", draft=True)]
    assert [r["tag_name"] for r in candidates(on_v1, "0.5.412")] == ["v1.1.0", "v1.0.9"]
    assert [r["tag_name"] for r in candidates(on_v1, "1.0.0")] == ["v1.1.0"]  # stable only


def test_whats_new_lists_every_release_since_mine_once():
    assert whats_new(RELEASES, "0.5.405") == [
        "Grímsvötn is now **recognized**.",
        "A quiet chat no longer splits a match.",
        "(+ 1 behind-the-scenes change)",
    ]
    many = [release(f"v0.6.{n}", f"Change {n}.") for n in range(30, 0, -1)]
    notes = whats_new(many, "0.5.0")
    assert len(notes) == NOTES_CAP + 1 and notes[-1] == f"... and {30 - NOTES_CAP} more"


def test_a_newer_version_is_found_and_logged(caplog):
    caplog.set_level(logging.INFO, "yaptracker.updates")
    check = UpdateCheck("0.5.405", lambda: True, fetch=lambda: RELEASES, clock=lambda: 1000.0)
    found = check.check()
    assert (found.newest, check.newest) == ("v0.5.412", "v0.5.412")
    assert found.notes[0] == "Grímsvötn is now **recognized**."
    assert "update: v0.5.412 is out (this is v0.5.405)" in caplog.text
    up_to_date = UpdateCheck("0.5.412", lambda: True, fetch=lambda: RELEASES)
    assert up_to_date.check().newest is None and "update: up to date (v0.5.412)" in caplog.text


def test_offline_is_one_log_line_and_no_banner(caplog):
    caplog.set_level(logging.INFO, "yaptracker.updates")

    def offline():
        raise urllib.error.URLError("getaddrinfo failed")

    check = UpdateCheck("0.5.405", lambda: True, fetch=offline)
    found = check.check()
    assert check.newest is None and "getaddrinfo failed" in found.error
    assert caplog.text.count("update: check failed (URLError") == 1


def test_once_a_day_never_in_a_match_and_switchable():
    now, in_match, on = [0.0], [True], [True]
    check = UpdateCheck("0.5.405", lambda: on[0], busy=lambda: in_match[0],
                        fetch=lambda: RELEASES, clock=lambda: now[0])  # fmt: skip
    assert not check.due()  # in a match: after it
    in_match[0] = False
    assert check.due()
    check.check()
    now[0] = DAY_S - 1
    assert not check.due()
    now[0] = DAY_S
    assert check.due()
    on[0] = False
    assert not check.due()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_live_shows_the_banner_until_later(user: User, monkeypatch):
    config.save_setup_state("done")
    check = UpdateCheck("0.5.405", lambda: True, fetch=lambda: RELEASES)
    monkeypatch.setattr(runtime, "updates", check)
    await user.open("/")
    (banner,) = user.find(marker="update").elements
    assert "yt-hidden" in banner.classes  # never checked: nothing to say
    check.check()
    await user.should_see("YapTracker v0.5.412 is out.")
    user.find(marker="update-notes").click()
    await user.should_see("Grímsvötn is now recognized.")
    user.find(marker="update-later").click()
    assert "yt-hidden" in banner.classes


async def test_about_checks_now_and_has_the_switch(user: User, monkeypatch):
    config.save_setup_state("done")
    check = UpdateCheck("0.5.412", lambda: True, fetch=lambda: RELEASES)
    monkeypatch.setattr(runtime, "updates", check)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("I look for a newer version once a day.")
    user.find(marker="update-check").click()
    await user.should_see("Up to date (v0.5.412), checked at")
    user.find(marker="update-switch").click()
    assert config.update_check() is False


def test_update_now_runs_from_the_install_root_only(monkeypatch, tmp_path):
    from yaptracker import updates

    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "executable", "/x/YapTracker/app/YapTracker.exe")
    assert updates.install_root() == Path("/x/YapTracker")
    monkeypatch.setattr(updates.sys, "executable", "/x/Downloads/YapTracker/YapTracker.exe")
    assert updates.install_root() is None  # unpacked somewhere else: update.ps1 by hand
    assert "Only in the installed YapTracker" in updates.cannot_update_now()
    assert updates.cannot_update_now(match_running=True) == "Updates wait until the match is over."
    with pytest.raises(RuntimeError):
        updates.start_update("v0.5.412")


def test_update_now_copies_the_script_to_temp_and_starts_it(monkeypatch, tmp_path):
    from yaptracker import updates

    script = tmp_path / "bundle" / "update.ps1"
    script.parent.mkdir()
    script.write_text("param($InstallRoot)", encoding="ascii")
    started = []
    monkeypatch.setattr(updates, "bundled_script", lambda: script)
    monkeypatch.setattr(updates, "install_root", lambda: Path("/x/O'Brien/YapTracker"))
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updates.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    updates.start_update("v0.5.412")
    copy = tmp_path / "YapTracker-update.ps1"
    assert copy.read_text(encoding="ascii") == "param($InstallRoot)"
    (cmd,) = started
    assert cmd[:2] == ["powershell.exe", "-NoProfile"]
    assert f"& '{copy}' -InstallRoot '/x/O''Brien/YapTracker'" in cmd[-1]  # quoted for PowerShell
    assert "Start-Process '/x/O''Brien/YapTracker/app/YapTracker.exe'" in cmd[-1]


async def test_update_now_waits_for_the_match_and_says_why_it_cant(user: User, monkeypatch):
    from yaptracker import updates
    from yaptracker.ui import updates as ui_updates

    config.save_setup_state("done")
    check = UpdateCheck("0.5.405", lambda: True, fetch=lambda: RELEASES)
    check.check()
    monkeypatch.setattr(runtime, "updates", check)
    await user.open("/")
    await user.should_see("YapTracker v0.5.412 is out.")
    button = next(iter(user.find(marker="update-now").elements))
    assert "Only in the installed YapTracker" in button.props["title"]  # this is a source run
    calls = []
    monkeypatch.setattr(updates, "cannot_update_now", lambda running: None)
    monkeypatch.setattr(updates, "start_update", lambda newest: calls.append(newest))
    monkeypatch.setattr(ui_updates, "quit_app", lambda: calls.append("quit"))
    await asyncio.sleep(1.2)  # the button looks again every second
    assert "disabled" not in button.props
    user.find(marker="update-now").click()
    await user.should_see("Updating: YapTracker closes now and is back in a minute.")
    assert calls[0] == "v0.5.412"
