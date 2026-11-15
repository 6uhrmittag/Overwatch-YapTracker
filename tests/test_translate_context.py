"""DeepL gets the lines before as context, so slang translates better (#538): only their text,
never a name or an id; turned down once, never sent again. Gamer shorthand alone is never sent.
Made-up lines and names; a fake DeepL answers, no network."""

import io
import json
import time
import urllib.error

import pytest

from yaptracker import translate
from yaptracker.auto_translate import AutoTranslate, context_for
from yaptracker.store.repo import Store
from yaptracker.translate import SHORT, DeepL, FakeTranslator, only_shorthand

KEY = "00000000-0000-0000-0000-000000000000:fx"  # made up
NOW = time.time()


class FakeDeepL:
    """Keeps every request body; `refuse_context`: answers 400 to one with a context."""

    def __init__(self, refuse_context=False):
        self.sent, self.refuse_context = [], refuse_context

    def __call__(self, request):
        body = json.loads(request.data)
        self.sent.append(body)
        if self.refuse_context and "context" in body:
            raise urllib.error.HTTPError(translate.URL, 400, "no", {}, io.BytesIO(b""))
        return {"translations": [{"detected_source_language": "ES", "text": f"[{t}]"}
                                 for t in body["text"]]}  # fmt: skip


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
def match(store):
    return store.start_match(store.start_session(NOW), NOW, "heroselect")


def say(store, match, text, channel="match", **kwargs):
    kwargs.setdefault("speaker_raw", "Kettle")
    return store.add_message(ts=NOW, channel=channel, text=text, match_id=match, **kwargs)


def test_the_context_is_the_text_of_the_lines_before_in_the_same_channel(store, match):
    say(store, match, "Kettle started playing Overwatch.", channel="system", speaker_raw=None)
    say(store, match, "push the cart", channel="team", speaker_raw="Biscuit")
    say(store, match, "Ultimate is ready", hero="Kiriko")  # comms wheel: the game's words
    for n in range(7):
        say(store, match, f"vamos chicos {n}", speaker_raw=f"Kettle{n}")
    line = store.message(say(store, match, "que onda con el tanque"))
    context = context_for(store, line)
    assert context == "\n".join(f"vamos chicos {n}" for n in range(2, 7))  # the last 5
    assert "Kettle" not in context and "Overwatch" not in context and "Ultimate" not in context


def test_few_lines_in_its_channel_take_the_whole_match(store, match):
    say(store, match, "hola a todos", channel="team")
    say(store, match, "buenas")
    line = store.message(say(store, match, "que onda con el tanque"))
    assert context_for(store, line) == "hola a todos\nbuenas"
    assert context_for(store, store.message(say(store, None, "sin partida"))) is None


def test_auto_translate_sends_the_context_with_the_lines(store, match):
    fake = FakeDeepL()
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    auto = AutoTranslate(lambda: store, lambda: deepl, lambda: True, lambda: {"EN", "DE"})
    say(store, match, "bro")
    auto.step()  # starts from now
    say(store, match, "alguien habla español")
    say(store, match, "que pasa con el tanque")
    assert auto.step() == 2
    (body,) = fake.sent
    assert body["text"] == ["alguien habla español", "que pasa con el tanque"]
    assert body["context"] == "bro"
    assert set(body) <= {"text", "target_lang", "context", "tag_handling", "ignore_tags"}


def test_a_refused_context_is_dropped_for_the_rest_of_the_run():
    fake = FakeDeepL(refuse_context=True)
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    assert deepl.translate("buenas curas", "hola").text == "[buenas curas]"
    assert deepl.translate("que pasa", "hola").text == "[que pasa]"
    assert ["context" in body for body in fake.sent] == [True, False, False]


@pytest.mark.parametrize("line", ["gg", "gg ez", "GGGG!", "xD lol", "ggwp ◇", "lmaooo", "ty np"])
def test_shorthand_alone_is_never_sent(line):
    fake = FakeDeepL()
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    assert only_shorthand(line)
    assert deepl.translate(line).error == SHORT
    assert fake.sent == []
    assert FakeTranslator().translate(line).error == SHORT


@pytest.mark.parametrize("line", ["gg buenas curas", "hola", "no", "ok vamos", "◇", ""])
def test_a_line_with_words_is_not_shorthand(line):
    assert not only_shorthand(line)


def test_shorthand_inside_a_line_comes_back_as_typed():
    fake = FakeDeepL()
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    done = deepl.translate("gg, buenas curas & <3")
    (body,) = fake.sent
    assert body["text"] == ["<x>gg,</x> buenas curas &amp; &lt;3"]
    assert (body["tag_handling"], body["ignore_tags"]) == ("xml", ["x"])
    assert done.text == "[gg, buenas curas & <3]"


def test_auto_translate_never_sends_a_shorthand_line(store, match):
    fake = FakeDeepL()
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    auto = AutoTranslate(lambda: store, lambda: deepl, lambda: True, lambda: {"EN"})
    auto.step()
    say(store, match, "gg ez")
    assert auto.step() == 0
    assert fake.sent == []
