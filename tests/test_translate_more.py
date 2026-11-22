"""Every line that isn't clearly in a language you read goes to DeepL (#567): its detected
language decides, a line with nothing to translate is remembered, and the month's free characters
are counted. Made-up lines and names; a fake DeepL answers, no network."""

import io
import json
import logging
import time
import urllib.error

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, export, runtime, translate
from yaptracker.auto_translate import AutoTranslate, why_not
from yaptracker.languages import skip
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.translate import DeepL, Usage
from yaptracker.ui import shell
from yaptracker.ui.line_actions import looked_at
from yaptracker.ui.translate_card import usage_words

KEY = "00000000-0000-0000-0000-000000000000:fx"  # made up
READ = {"EN", "DE"}
NOW = time.time()
FOREIGN = {"majeur et vacine": "major and vaccine", "que pasa": "what's up"}


class FakeDeepL:
    """api-free.deepl.com: /v2/usage counts, /v2/translate knows two foreign lines, gives hero
    names back as they came (as French) and calls the rest English."""

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
        return {"translations": [
            {"detected_source_language": "FR", "text": FOREIGN[t]} if t in FOREIGN
            else {"detected_source_language": "FR", "text": t} if t == "Zarya Winston"
            else {"detected_source_language": "EN", "text": t.upper()} for t in texts]}  # fmt: skip


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def auto(store, fake, clock=lambda: 0.0):
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake, clock=clock)
    translator = AutoTranslate(lambda: store, lambda: deepl, lambda: True, lambda: READ, clock)
    translator.step()  # just started: from now on
    return translator, deepl


def say(store, text, **kwargs):
    kwargs.setdefault("speaker_raw", "Kettle")
    return store.add_message(ts=NOW, channel=kwargs.pop("channel", "match"), text=text, **kwargs)


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("majeur et vacine", None),  # the line from the issue: no word the old check knew
        ("que pasa", None),  # two words are enough
        ("dziękuję", None),  # or eight letters
        ("nice ult", None),  # not clearly English: DeepL decides
        ("gg buenas curas", None),
        ("can we group up please", "a language you read"),
        ("danke für die heals", "a language you read"),
        ("hola", "short"),
        ("gg wp", "shorthand"),
        ("xD ◇", "shorthand"),
        ("◇ 123", "no words"),
    ],
)
def test_a_line_is_sent_unless_its_clearly_a_language_you_read(line, why):
    assert skip(line, READ) == why


def test_a_language_you_added_is_left_alone_too():
    assert skip("merci pour les soins", READ) is None
    assert skip("merci pour les soins", READ | {"FR"}) == "a language you read"


def test_a_short_french_line_translates_itself(store):
    fake = FakeDeepL()
    translator, _ = auto(store, fake)
    french = say(store, "majeur et vacine")
    mine = say(store, "que pasa", role="me")
    callout = say(store, "que pasa", hero="Kiriko")
    assert translator.step() == 1 and fake.sent == [["majeur et vacine"]]
    assert translator.known(french).text == "major and vaccine"
    kept = store.message(french)
    assert (kept.translation, kept.translation_from, kept.translation_to) == (
        "major and vaccine", "FR", "EN")  # fmt: skip
    assert why_not(store.message(mine), READ) == "yours or your crew's"
    assert why_not(store.message(callout), READ) == "the game's own words"


def test_what_deepl_calls_english_is_not_shown_and_not_sent_again(store):
    fake = FakeDeepL()
    translator, _ = auto(store, fake)
    english = say(store, "nice ult")
    names = say(store, "Zarya Winston")  # comes back as it went: nothing to show either
    assert translator.step() == 2
    assert translator.known(english) is None and translator.known(names) is None
    kept = store.message(english)
    assert (kept.translation, kept.translation_from, kept.translation_to) == (None, "EN", "EN")
    assert store.message(names).translation is None
    # remembered with the line, so also after a restart: not by itself, not with a click
    assert why_not(kept, READ) == "looked at before"
    assert looked_at(kept, "EN").error == "DeepL reads this as English: nothing to translate."
    assert looked_at(kept, "DE") is None  # into German is another question
    assert why_not(store.message(names), READ) == "looked at before"
    assert looked_at(store.message(names), "EN") is None  # read better since, maybe: a click asks
    # nowhere a translation: search, and the export keeps its documented shape
    assert [m.id for m in store.search("nice")] == [english]
    record = export._message(kept)
    assert (record["translation"], record["translation_from"], record["translation_to"]) == (
        None, None, None)  # fmt: skip


def test_a_translation_is_never_replaced_by_nothing_to_translate(store):
    said = say(store, "que pasa")
    store.set_translation(said, "what's up", "ES", "EN")
    store.set_not_foreign(said, "EN", "EN")
    assert store.message(said).translation_from == "ES"


def test_the_decisions_are_logged_without_the_line_or_a_name(store, caplog):
    caplog.set_level(logging.DEBUG, "yaptracker.auto_translate")
    translator, _ = auto(store, FakeDeepL())
    say(store, "majeur et vacine")
    say(store, "can we group up please")
    say(store, "gg wp", speaker_raw="Pickle")
    translator.step()
    assert "a line of 16 characters sent" in caplog.text
    assert "a line of 22 characters not sent: a language you read" in caplog.text
    assert "a line of 5 characters not sent: shorthand" in caplog.text
    assert "translate: auto: 1 translated of 1 line(s) sent" in caplog.text
    for private in ("majeur", "group", "Kettle", "Pickle"):
        assert private not in caplog.text


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
    assert deepl.translate("que pasa").text == "what's up"  # a click still works


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


def test_a_failure_is_only_said_under_clearly_foreign_lines(store):
    fake = FakeDeepL(error=urllib.error.URLError("offline"))
    translator, _ = auto(store, fake)
    unclear = say(store, "nice ult")
    spanish = say(store, "gg buenas curas amigos")
    translator.step()
    assert translator.known(unclear) is None
    assert translator.known(spanish).error == translate.OFFLINE


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
    await user.should_see("every line from others that isn't clearly in a language you read")
    assert config.translate_auto() is True  # a saved choice stays as it is


async def test_a_click_on_a_line_deepl_called_english_says_so_without_asking(
    user: User, store, monkeypatch
):
    config.save_setup_state("done")
    config.save_translate_chat(True)
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(NOW)
    tracker.new_match()
    said = say(store, "nice ult", match_id=tracker.match_id)
    store.set_not_foreign(said, "EN", "EN")
    fake = FakeDeepL()
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "translator", DeepL(lambda: KEY, lambda: "EN", send=fake))
    await user.open("/")
    await user.should_see("nice ult")
    await user.should_not_see("nothing to translate")
    user.find(marker="translate-line").click()
    await user.should_see("DeepL reads this as English: nothing to translate.")
    assert fake.sent == []
