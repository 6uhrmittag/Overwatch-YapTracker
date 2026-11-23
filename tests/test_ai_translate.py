"""AI translation via OpenRouter (#568): only the lines' text and the text before them go out,
only to providers that keep nothing; "=" means nothing to translate; a slow or failed AI hands
over to DeepL; the monthly limit stops it. A fake OpenRouter answers: no network. Made-up lines
and names."""

import io
import json
import time
import urllib.error

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import ai_translate, config, runtime
from yaptracker.ai_translate import Engines, OpenRouter, Spend, parse
from yaptracker.auto_translate import AutoTranslate, context_for, outgoing
from yaptracker.store.repo import Store
from yaptracker.translate import SHORT, DeepL, Translation, Usage
from yaptracker.ui import shell
from yaptracker.ui.ai_settings import spend_words

KEY = "sk-or-v1-0000000000000000"  # made up
DEEPL_KEY = "00000000-0000-0000-0000-000000000000:fx"  # made up
READ = {"EN", "DE"}
NOW = time.time()


class FakeOpenRouter:
    """openrouter.ai: French and Spanish lines translated, English ones answered with "="."""

    def __init__(self, error=None, cost=0.0001):
        self.sent, self.timeouts, self.error, self.cost = [], [], error, cost

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        self.sent.append(body)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        asked = body["messages"][1]["content"].split("Lines:\n", 1)[1].splitlines()
        lines = [line.split(". ", 1)[1] for line in asked]
        found = [{"l": "es", "x": f"[{t}] in English"} if "curas" in t
                 else {"l": "fr", "x": f"[{t}] in English"} if "merci" in t or "vacine" in t
                 else {"l": "en", "x": "="} for t in lines]  # fmt: skip
        fenced = "```json\n" + json.dumps({"t": found}) + "\n```"  # models like code fences
        return {"choices": [{"message": {"content": fenced}}], "usage": {"cost": self.cost}}


class FakeDeepL:
    def __init__(self):
        self.sent = []

    def __call__(self, request):
        texts = json.loads(request.data)["text"]
        self.sent.append(texts)
        return {"translations": [{"detected_source_language": "FR", "text": f"<{t}> by DeepL"}
                                 for t in texts]}  # fmt: skip


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def ai(tmp_path, fake, cap=1.0, key=KEY):
    return OpenRouter(lambda: key, lambda: "EN", lambda: ai_translate.DEFAULT_MODEL,
                      lambda: cap, Spend(tmp_path / "ai_spend.json"), send=fake)  # fmt: skip


def engines(tmp_path, fake_ai, fake_deepl, deepl_key=DEEPL_KEY, cap=1.0):
    deepl = DeepL(lambda: deepl_key, lambda: "EN", send=fake_deepl)
    return Engines(deepl, ai(tmp_path, fake_ai, cap), lambda: "ai", lambda: bool(deepl_key))


def say(store, text, match_id, speaker="Kettle", **kwargs):
    return store.add_message(ts=NOW, channel=kwargs.pop("channel", "match"), text=text,
                             speaker_raw=speaker, match_id=match_id, **kwargs)  # fmt: skip


def test_only_text_goes_out_with_the_lines_before_and_only_to_providers_that_keep_nothing(
    store, tmp_path
):
    session = store.start_session(NOW)
    match = store.start_match(session, NOW, "heroselect")
    say(store, "push the cart", match, speaker="Zappy")
    say(store, "Zappy endorsed Kettle!", match, channel="system", speaker=None)
    line = store.message(say(store, "majeur et vacine", match, speaker="Kettle"))
    fake = FakeOpenRouter()
    found = ai(tmp_path, fake).translate(outgoing(line.text), context_for(store, line))
    assert found == Translation("[majeur et vacine] in English", "French", code="FR")
    (body,) = fake.sent
    assert body["provider"] == ai_translate.PROVIDER == {
        "zdr": True, "data_collection": "deny", "ignore": ["google-vertex"]}  # fmt: skip
    assert body["model"] == ai_translate.DEFAULT_MODEL and body["usage"] == {"include": True}
    assert body["models"] == [ai_translate.DEFAULT_MODEL, ai_translate.FALLBACK_MODEL]
    sent = json.dumps(body["messages"])
    assert "push the cart" in sent and "majeur et vacine" in sent
    assert "Zappy" not in sent and "Kettle" not in sent  # names never go out
    assert fake.timeouts == [pytest.approx(ai_translate.TIMEOUT_S + 0.1)]


def test_a_system_row_glued_onto_a_line_is_cut_before_it_is_sent():
    assert outgoing("gg wp Zappy endorsed Kettle!") == "gg wp"
    assert outgoing("glhf Kettle switched to Ana (was Mercy).") == "glhf"
    assert outgoing("merci pour les soins") == "merci pour les soins"
    assert outgoing("ggwp Zappy endorsed-Kettle!") == "ggwp"  # OCR's misread of the row
    assert outgoing("Kettle started playing Overwatch.") == ""
    for talk in ("he endorsed me lol", "nosotros started playing tarde jaja",
                 "i switched to tank (was bored)"):  # fmt: skip
        assert outgoing(talk) == talk  # somebody talking: kept whole


def test_already_in_the_target_language_is_nothing_to_translate(store, tmp_path):
    fake = FakeOpenRouter()
    session = store.start_session(NOW)
    match = store.start_match(session, NOW, "heroselect")
    router = ai(tmp_path, fake)
    auto = AutoTranslate(lambda: store, lambda: router, lambda: True, lambda: READ)
    auto.step()
    english = say(store, "anyone up for ranked", match)  # the local check isn't sure
    french = say(store, "merci pour les soins", match)
    assert auto.step() == 2 and len(fake.sent) == 1  # one request for both
    assert auto.known(english) is None and auto.known(french).source == "French"
    assert store.message(english).translation_from == "EN"  # remembered: never sent again
    assert store.message(english).translation is None


def test_an_odd_answer_is_a_failed_line_not_a_wrong_translation():
    with pytest.raises(ValueError):
        parse('{"t": [{"l": "fr", "x": "one"}]}', ["a", "b"], "EN")  # 1 answer for 2 lines
    assert parse('{"t": [{"l": "", "x": "="}]}', ["gg ez"], "DE") == [
        Translation("gg ez", "German", code="DE")
    ]


@pytest.mark.parametrize("error", [TimeoutError(), TimeoutError(),
                                   urllib.error.URLError("offline")])  # fmt: skip
def test_a_slow_or_unreachable_ai_hands_over_to_deepl(tmp_path, error):
    fake_ai, fake_deepl = FakeOpenRouter(error=error), FakeDeepL()
    found = engines(tmp_path, fake_ai, fake_deepl).translate("merci pour les soins")
    assert found.text == "<merci pour les soins> by DeepL" and fake_deepl.sent


def test_without_a_deepl_key_the_line_says_why(tmp_path):
    fake_ai = FakeOpenRouter(error=TimeoutError())
    found = engines(tmp_path, fake_ai, FakeDeepL(), deepl_key="").translate("merci pour")
    assert found.error == ai_translate.OFFLINE


def test_the_monthly_limit_stops_the_ai_and_deepl_takes_over(tmp_path):
    fake_ai, fake_deepl = FakeOpenRouter(cost=0.6), FakeDeepL()
    both = engines(tmp_path, fake_ai, fake_deepl, cap=1.0)
    assert both.translate("merci pour les soins").source == "French"
    assert both.translate("gracias por las curas").source == "Spanish"
    assert both.ai.spend.used() == pytest.approx(1.2)  # over the limit: no more AI requests
    third = both.translate("merci beaucoup les amis")
    assert len(fake_ai.sent) == 2 and third.text == "<merci beaucoup les amis> by DeepL"
    alone = engines(tmp_path, fake_ai, fake_deepl, deepl_key="", cap=1.0)
    assert alone.translate("merci encore").error == ai_translate.capped(1.0)


def test_the_spend_is_kept_and_a_new_month_starts_at_zero(tmp_path):
    now = {"t": time.mktime((2026, 11, 30, 12, 0, 0, 0, 0, -1))}
    spend = Spend(tmp_path / "ai_spend.json", clock=lambda: now["t"])
    spend.add(0.25)
    spend.add(0.5)
    assert Spend(tmp_path / "ai_spend.json", clock=lambda: now["t"]).used() == 0.75
    now["t"] += 2 * 86400  # December
    assert spend.used() == 0.0
    spend.add(0.1)
    assert spend.used() == pytest.approx(0.1)


def test_only_the_default_model_has_a_fallback():
    picked = json.loads(ai_translate.request(KEY, "mistralai/some-model", ["merci"], "EN").data)
    assert "models" not in picked  # a model the user chose fails in words, never swapped
    assert picked["provider"]["ignore"] == ["google-vertex"]


def test_wrong_key_and_no_zdr_provider_say_so(tmp_path):
    for code, said in ((401, ai_translate.WRONG_KEY), (404, ai_translate.NO_ZDR),
                       (402, ai_translate.NO_CREDIT)):  # fmt: skip
        error = urllib.error.HTTPError(ai_translate.URL, code, "no", {}, None)
        assert ai(tmp_path, FakeOpenRouter(error=error)).translate("merci").error == said
    assert ai(tmp_path, FakeOpenRouter(), key="").translate("merci").error == ai_translate.NO_KEY


def test_deepl_stays_the_default_and_its_usage_pauses_only_deepl(tmp_path):
    assert config.translate_engine() == "deepl"
    deepl = DeepL(lambda: DEEPL_KEY, lambda: "EN", send=FakeDeepL())
    both = Engines(deepl, ai(tmp_path, FakeOpenRouter()), config.translate_engine, lambda: True)
    assert both.name == "DeepL"
    config.save_translate_engine("ai")
    assert both.name == "the AI" and both.usage() is None  # the AI's limit is its own


def test_spend_in_words():
    assert spend_words(0.0412, 1.0) == "AI: $0.04 of $1.00 used this month."
    assert "limit is reached" in spend_words(1.0, 1.0)
    assert spend_words(None, 1.0).startswith("AI: what this month")


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_settings_choose_the_ai_its_key_model_and_limit(user: User, tmp_path, monkeypatch):
    config.save_setup_state("done")
    monkeypatch.setattr(runtime, "translator", engines(tmp_path, FakeOpenRouter(), FakeDeepL()))
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see(marker="translate-engine")
    (block,) = user.find(marker="ai-settings").elements
    assert "yt-hidden" in block.classes  # DeepL: nothing about the AI
    user.find(marker="engine-ai").click()
    assert config.translate_engine() == "ai" and "yt-hidden" not in block.classes
    user.find(marker="openrouter-key").type(KEY).trigger("blur")
    assert config.openrouter_key() == KEY
    user.find(marker="ai-cap").clear().type("2,50").trigger("blur")
    assert config.ai_cap() == 2.5
    user.find(marker="ai-cap").clear().type("lots").trigger("blur")
    assert config.ai_cap() == 2.5  # not a number: the saved one stays
    await user.should_see("AI: $0.00 of $2.50 used this month.")
    user.find(marker="engine-deepl").click()
    assert config.translate_engine() == "deepl" and "yt-hidden" in block.classes


def test_a_model_that_must_think_is_asked_again_with_a_little_thinking(tmp_path):
    """Thinking off is quicker and cheaper; some models refuse it (#568)."""

    class Thinker(FakeOpenRouter):
        def __call__(self, request, timeout):
            if json.loads(request.data)["reasoning"] == ai_translate.NO_THINKING:
                self.sent.append("refused")
                body = b'{"error": {"message": "Reasoning is mandatory for this endpoint"}}'
                raise urllib.error.HTTPError(ai_translate.URL, 400, "no", {}, io.BytesIO(body))
            return super().__call__(request, timeout)

    fake = Thinker()
    router = ai(tmp_path, fake)
    assert router.translate("merci pour les soins").source == "French"
    assert router.translate("gracias por las curas").source == "Spanish"
    assert fake.sent[0] == "refused" and len(fake.sent) == 3  # refused once, then remembered
    assert fake.sent[1]["reasoning"] == ai_translate.LITTLE_THINKING
    assert fake.sent[1]["max_tokens"] > fake.sent[2]["max_tokens"] - 1  # room to think


def test_by_default_the_model_answers_without_thinking(tmp_path):
    fake = FakeOpenRouter()
    ai(tmp_path, fake).translate("merci pour les soins")
    assert fake.sent[0]["reasoning"] == {"enabled": False}


@pytest.mark.parametrize("content", [None, [{"type": "text"}], '{"t": [{"l": "es", "x": null}]}',
                                     '{"t": "nope"}'])  # fmt: skip
def test_an_answer_without_usable_text_is_a_failed_line_and_deepl_takes_it(tmp_path, content):
    class Empty(FakeOpenRouter):
        def __call__(self, request, timeout):
            super().__call__(request, timeout)
            return {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.0001}}

    alone = ai(tmp_path, Empty())
    assert alone.translate("gracias por las curas").error == ai_translate.FAILED
    both = engines(tmp_path, Empty(), FakeDeepL())
    assert both.translate("gracias por las curas").text == "<gracias por las curas> by DeepL"


def test_a_timed_out_request_still_counts_against_the_limit(tmp_path):
    fake = FakeOpenRouter(cost=0.0004)
    router = ai(tmp_path, fake)
    router.translate("merci pour les soins")  # 0.0004 for one line
    fake.error = TimeoutError()
    router.translate_many(["merci beaucoup", "gracias amigos"])
    assert router.spend.used() == pytest.approx(0.0004 + 2 * 0.0004)  # billed anyway: guessed


def test_a_thinking_model_gets_more_time(tmp_path):
    class Thinker(FakeOpenRouter):
        def __call__(self, request, timeout):
            if json.loads(request.data)["reasoning"] == ai_translate.NO_THINKING:
                body = b'{"error": {"message": "Reasoning is mandatory"}}'
                raise urllib.error.HTTPError(ai_translate.URL, 400, "no", {}, io.BytesIO(body))
            return super().__call__(request, timeout)

    fake = Thinker()
    ai(tmp_path, fake).translate("merci pour les soins")
    assert fake.timeouts == [ai_translate.THINKING_TIMEOUT_S]


def test_shorthand_says_so_with_the_ai_too(tmp_path):
    fake = FakeOpenRouter()
    assert ai(tmp_path, fake).translate("gg ez wp").error == SHORT and not fake.sent


def test_deepl_near_its_limit_or_failing_too_leaves_the_ais_reason(tmp_path):
    class NearDeepL(DeepL):
        def usage(self, ask=True):
            return Usage(490_000)

    fake_deepl = FakeDeepL()
    near = Engines(NearDeepL(lambda: DEEPL_KEY, lambda: "EN", send=fake_deepl),
                   ai(tmp_path, FakeOpenRouter(error=TimeoutError())), lambda: "ai",
                   lambda: True)  # fmt: skip
    assert near.translate("merci pour").error == ai_translate.OFFLINE and not fake_deepl.sent

    class Broken(FakeDeepL):
        def __call__(self, request):
            raise urllib.error.URLError("down too")

    both = engines(tmp_path, FakeOpenRouter(error=TimeoutError()), Broken())
    assert both.translate("merci pour").error == ai_translate.OFFLINE  # not DeepL's message


def test_the_auto_thread_and_a_click_cant_both_slip_under_the_limit(tmp_path):
    import threading

    gate = threading.Event()

    class Slow(FakeOpenRouter):
        def __call__(self, request, timeout):
            gate.wait(1)
            return super().__call__(request, timeout)

    fake = Slow(cost=0.6)
    router = ai(tmp_path, fake, cap=1.0)
    router.spend.add(0.5)
    first = threading.Thread(target=router.translate, args=("merci pour les soins",))
    first.start()
    time.sleep(0.05)
    gate.set()
    second = router.translate("gracias por las curas")  # waits for the first, then sees the cap
    first.join()
    assert len(fake.sent) == 1 and second.error == ai_translate.capped(1.0)
