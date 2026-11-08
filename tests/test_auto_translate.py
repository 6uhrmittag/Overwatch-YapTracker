"""Foreign lines translate themselves (#469): a local language check, then DeepL in the
background, only for other players' lines in a language you don't read. Made-up lines and names;
a fake DeepL answers, no network."""

import json
import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime, translate
from yaptracker.auto_translate import AutoTranslate
from yaptracker.languages import foreign
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.translate import DeepL, Translation
from yaptracker.ui import shell

KEY = "00000000-0000-0000-0000-000000000000:fx"  # made up
READ = {"EN", "DE"}
NOW = time.time()


@pytest.mark.parametrize(
    ("line", "language"),
    [
        ("gg buenas curas", "ES"),
        ("alguien habla español", "ES"),
        ("que pasa con el tanque", "ES"),
        ("merci pour les soins", "FR"),
        ("c'est quoi ce tank", "FR"),
        ("bien joué à tous", "FR"),
        ("dzięki za leczenie", "PL"),
        ("grajcie razem prosze", "PL"),
        ("obrigado pelas curas", "PT"),
        ("grazie per le cure", "IT"),
        # left alone: English, German, slang, short, names
        ("can we group up please", None),
        ("rein go in now", None),
        ("Kettle you are a legend", None),
        ("schöne grüße aus berlin", None),
        ("danke für die heals", None),
        ("wie gehts euch so heute", None),
        ("gg wp", None),
        ("xD", None),
        ("hola", None),
        ("la la la la", None),
        ("no no no no", None),
    ],
)
def test_only_lines_confidently_in_a_language_you_dont_read(line, language):
    assert foreign(line, READ) == language


def test_a_language_you_read_is_left_alone():
    assert foreign("merci pour les soins", READ | {"FR"}) is None


class FakeDeepL:
    """api-free.deepl.com: ES and FR lines translated, anything else said to be English."""

    def __init__(self, error=None):
        self.sent, self.error = [], error

    def __call__(self, request):
        texts = json.loads(request.data)["text"]
        self.sent.append(texts)
        if self.error is not None:
            raise self.error
        return {"translations": [
            {"detected_source_language": "ES" if "curas" in t else "FR" if "merci" in t
             else "EN", "text": f"<{t}>"} for t in texts]}  # fmt: skip


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def auto(store, fake, on=lambda: True, read=lambda: READ, clock=lambda: 0.0):
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    return AutoTranslate(lambda: store, lambda: deepl, on, read, clock=clock)


def say(store, text, **kwargs):
    kwargs.setdefault("speaker_raw", "Kettle")
    return store.add_message(ts=NOW, channel=kwargs.pop("channel", "match"), text=text, **kwargs)


def test_new_foreign_lines_of_others_go_together_and_each_once(store):
    fake = FakeDeepL()
    before = say(store, "gg buenas curas")
    translator = auto(store, fake)
    assert translator.step() == 0  # just started: nothing from before
    spanish = say(store, "gg buenas curas amigos")
    french = say(store, "merci pour les soins")
    english = say(store, "can we group up please")
    mine = say(store, "gracias por las curas", role="me")
    crew = say(store, "merci pour tout le monde", role="crew")
    system = say(store, "Merci pour les soins!", channel="system", speaker_raw=None)
    callout = say(store, "que pasa con el tanque", hero="Kiriko")
    assert translator.step() == 2
    assert fake.sent == [["gg buenas curas amigos", "merci pour les soins"]]  # one request
    assert translator.known(spanish) == Translation("<gg buenas curas amigos>", "Spanish",
                                                    code="ES")  # fmt: skip
    assert translator.known(french).source == "French"
    for left in (before, english, mine, crew, system, callout):
        assert translator.known(left) is None
    again = say(store, "merci pour les soins")
    assert translator.step() == 1 and len(fake.sent) == 1  # the same text: not sent again
    assert translator.known(again).source == "French"


def test_deepl_has_the_last_word_on_the_language(store):
    fake = FakeDeepL()
    translator = auto(store, fake)
    translator.step()
    looks_spanish = say(store, "que pasa con el tank")  # DeepL: English after all
    assert translator.step() == 1
    assert translator.known(looks_spanish) is None


def test_when_deepl_fails_the_lines_say_why_and_it_waits(store):
    now = {"t": 0.0}
    fake = FakeDeepL(error=translate.urllib.error.URLError("offline"))
    translator = auto(store, fake, clock=lambda: now["t"])
    translator.step()
    first = say(store, "gg buenas curas")
    translator.step()
    assert translator.known(first).error == translate.OFFLINE
    second = say(store, "merci pour les soins")
    now["t"] = 30.0
    translator.step()
    assert len(fake.sent) == 1  # no retry loop: still waiting
    assert translator.known(second).error == translate.OFFLINE
    fake.error = None
    now["t"] = 61.0
    third = say(store, "merci pour les soins encore")
    translator.step()
    assert translator.known(third).source == "French"


def test_switched_off_nothing_is_sent_and_on_again_starts_from_then(store):
    on = {"now": False}
    fake = FakeDeepL()
    translator = auto(store, fake, on=lambda: on["now"])
    translator.step()
    said = say(store, "gg buenas curas")
    assert translator.step() == 0 and fake.sent == []
    on["now"] = True
    translator.step()  # starts from now
    assert translator.step() == 0 and translator.known(said) is None


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_live_shows_a_translation_that_came_by_itself(user: User, store, monkeypatch):
    config.save_setup_state("done")
    config.save_translate_chat(True)
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(NOW)
    tracker.new_match()
    said = say(store, "gg buenas curas", match_id=tracker.match_id)
    found: dict = {}

    class Known:
        def known(self, message_id):
            return found.get(message_id)

    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "translator", translate.FakeTranslator())
    monkeypatch.setattr(runtime, "auto_translate", Known())
    await user.open("/")
    await user.should_see("gg buenas curas")
    found[said] = Translation("gg good heals", "Spanish", code="ES")  # arrives a moment later
    await user.should_see("↳ “gg good heals” (from Spanish)")


async def test_settings_i_read_and_automatic(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Cyrillic, Greek and Asian scripts aren't read")
    assert config.translate_auto() is True and config.read_languages() == {"EN", "DE"}
    user.find(marker="read-FR").click()
    assert config.read_languages() == {"EN", "DE", "FR"}
    user.find(marker="read-DE").click()
    assert config.read_languages() == {"EN", "FR"}
    user.find(marker="translate-auto-switch").click()
    assert config.translate_auto() is False
    config.save_translate_to("DE")
    assert "DE" in config.read_languages()  # the language translated into always counts


def test_no_key_yet_sent_nothing_so_a_pasted_key_works_at_once(store):
    """#469 review: "no key" started the 10-minute wait, though nothing went out."""
    key = {"now": ""}
    fake = FakeDeepL()
    deepl = DeepL(lambda: key["now"], lambda: "EN", send=fake)
    translator = AutoTranslate(lambda: store, lambda: deepl, lambda: True, lambda: READ,
                               clock=lambda: 0.0)  # fmt: skip
    translator.step()
    first = say(store, "gg buenas curas")
    translator.step()
    assert translator.known(first).error == translate.NO_KEY and fake.sent == []
    key["now"] = KEY
    second = say(store, "merci pour les soins")
    translator.step()
    assert translator.known(second).source == "French"


def test_a_dropped_connection_is_offline_not_a_lost_batch(store):
    import http.client

    fake = FakeDeepL(error=http.client.IncompleteRead(b""))
    translator = auto(store, fake)
    translator.step()
    said = say(store, "gg buenas curas")
    translator.step()
    assert translator.known(said).error == translate.OFFLINE


async def test_the_language_translated_into_stays_read_after_picking_others(user: User):
    """#469 review: picking Spanish while translating into English forgot English."""
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("I read")
    user.find(marker="read-ES").click()
    user.find(marker="read-EN").click()  # the target: stays read
    config.save_translate_to("DE")
    assert config.read_languages() == {"EN", "DE", "ES"}
