"""The month's free DeepL characters (#567): DeepL's own count in Settings, and near the limit
nothing translates by itself any more. Made-up lines and names; a fake DeepL answers, no
network."""

import io
import json
import time
import urllib.error

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime, translate
from yaptracker.auto_translate import AutoTranslate
from yaptracker.store.repo import Store
from yaptracker.translate import DeepL, Usage
from yaptracker.ui import shell
from yaptracker.ui.translate_card import usage_words

KEY = "00000000-0000-0000-0000-000000000000:fx"  # made up
NOW = time.time()


class FakeDeepL:
    """api-free.deepl.com: /v2/usage counts, /v2/translate calls everything French."""

    def __init__(self, used=1_000, limit=500_000, usage_error=None, error=None):
        self.used, self.limit, self.usage_error, self.error = used, limit, usage_error, error
        self.sent, self.asked = [], 0

    def __call__(self, request):
        if request.full_url == translate.USAGE_URL:
            assert request.data is None and request.get_method() == "GET"  # the key, no chat
            self.asked += 1
            if self.usage_error is not None:
                raise self.usage_error
            return {"character_count": self.used, "character_limit": self.limit}
        texts = json.loads(request.data)["text"]
        self.sent.append(texts)
        if self.error is not None:
            raise self.error
        return {"translations": [{"detected_source_language": "FR", "text": f"<{t}>"}
                                 for t in texts]}  # fmt: skip


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def auto(store, fake):
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake, clock=lambda: 0.0)
    translator = AutoTranslate(lambda: store, lambda: deepl, lambda: True,
                               lambda: {"EN", "DE"}, clock=lambda: 0.0)  # fmt: skip
    translator.step()  # just started: from now on
    return translator, deepl


def say(store, text):
    return store.add_message(ts=NOW, channel="match", text=text, speaker_raw="Kettle")


def test_usage_is_deepls_count_plus_what_was_sent_since():
    now = {"t": 0.0}
    fake = FakeDeepL(used=1_000)
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake, clock=lambda: now["t"])
    assert deepl.usage(ask=False) is None  # never asks from the UI thread
    assert deepl.usage() == Usage(1_000, 500_000)
    deepl.translate("que pasa")
    assert deepl.usage() == Usage(1_008, 500_000) and fake.asked == 1
    fake.used, now["t"] = 2_000, translate.USAGE_AGE_S + 1
    assert deepl.usage().used == 2_000 and fake.asked == 2  # asked again after 10 minutes
    assert DeepL(lambda: "", lambda: "EN", send=fake).usage() is None and fake.asked == 2


def test_near_the_free_limit_nothing_is_sent_by_itself(store):
    fake = FakeDeepL(used=480_000)
    translator, deepl = auto(store, fake)
    said = say(store, "majeur et vacine")
    assert translator.step() == 0 and fake.sent == []
    assert translator.known(said) is None
    assert "Translate automatically is paused" in usage_words(deepl.usage(ask=False))
    assert deepl.translate("que pasa").text == "<que pasa>"  # a click still works


def test_an_unknown_usage_pauses_nothing(store):
    fake = FakeDeepL(usage_error=urllib.error.URLError("offline"))
    translator, deepl = auto(store, fake)
    say(store, "majeur et vacine")
    assert translator.step() == 1 and fake.sent == [["majeur et vacine"]]
    assert deepl.usage(ask=False) is None and usage_words(None) == (
        "DeepL: the characters you used this month show here once your key works.")  # fmt: skip


def test_deepl_saying_its_used_up_pauses_and_a_click_says_why(store):
    used_up = urllib.error.HTTPError(translate.URL, 456, "no", {}, io.BytesIO(b""))
    fake = FakeDeepL(used=100, error=used_up)
    translator, deepl = auto(store, fake)
    say(store, "majeur et vacine")
    assert translator.step() == 1
    assert deepl.usage(ask=False).near
    assert deepl.translate("que pasa").error == translate.QUOTA


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_settings_show_the_months_characters(user: User, monkeypatch):
    config.save_setup_state("done")
    config.save_deepl_key(KEY)
    fake = FakeDeepL(used=41_250)
    monkeypatch.setattr(runtime, "translator", DeepL(config.deepl_key, lambda: "EN", send=fake))
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("DeepL: 41,250 of 500,000 characters used this month.")
