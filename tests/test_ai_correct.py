"""AI correction's client and triggers (#637). No real OpenRouter call: a fake `send`."""

import io
import json
import urllib.error

from yaptracker import ai_correct, ai_translate
from yaptracker.ai_translate import Spend

PNG = b"\x89PNG fake"


def answer(content: str, cost: float = 0.00005) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {"cost": cost}}


def corrector(tmp_path, replies, key="sk-test", limit=300, clock=lambda: 1_795_700_000.0):
    sent = []

    def send(req, timeout):
        body = json.loads(req.data)
        sent.append(body)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    c = ai_correct.Corrector(lambda: key, lambda: 1.0, Spend(tmp_path / "spend.json"),
                             limit=lambda: limit, send=send, clock=clock)  # fmt: skip
    return c, sent


def test_only_the_picture_goes_with_the_prompt_and_the_privacy_routing(tmp_path):
    c, sent = corrector(tmp_path, [answer('{"text": "[Pip]: gg", "icons": []}')])
    got = c.correct(PNG)
    assert (got.row, got.model, got.error) == ("[Pip]: gg", ai_correct.MODEL, None)
    (body,) = sent
    assert body["provider"] == ai_translate.PROVIDER  # zero retention, no Vertex (#583)
    (message,) = body["messages"]
    kinds = [part["type"] for part in message["content"]]
    assert kinds == ["text", "image_url"] and message["content"][0]["text"] == ai_correct.PROMPT
    assert message["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert c.spend.used() == 0.00005


def test_a_remark_after_the_json_and_a_leading_icon_are_left_out(tmp_path):
    content = '{"text": "◇ [Pip]: Thanks! ◇", "icons": ["thumbs up"]}\n\n{"note": "x"}'
    c, _ = corrector(tmp_path, [answer(content)])
    got = c.correct(PNG)
    assert got.row == "[Pip]: Thanks! ◇" and got.icons == ["thumbs up"]


def test_the_fallback_answers_when_the_default_fails(tmp_path):
    busy = urllib.error.HTTPError(ai_translate.URL, 429, "busy", {}, io.BytesIO(b""))
    c, sent = corrector(tmp_path, [busy, answer('{"text": "[Pip]: hi"}')])
    got = c.correct(PNG)
    assert got.row == "[Pip]: hi" and got.model == ai_correct.FALLBACK
    assert [b["model"] for b in sent] == [ai_correct.MODEL, ai_correct.FALLBACK]
    assert sent[1]["reasoning"] == ai_translate.LITTLE_THINKING  # Sonnet must think a little


def test_a_wrong_key_isnt_asked_again_with_the_fallback(tmp_path):
    wrong = urllib.error.HTTPError(ai_translate.URL, 401, "no", {}, io.BytesIO(b""))
    c, sent = corrector(tmp_path, [wrong])
    assert c.correct(PNG).error == ai_translate.WRONG_KEY and len(sent) == 1


def test_no_key_sends_nothing(tmp_path):
    c, sent = corrector(tmp_path, [], key="")
    assert c.correct(PNG).error == ai_translate.NO_KEY and sent == []


def test_the_evening_limit_and_the_monthly_cap_stop_it(tmp_path):
    c, sent = corrector(tmp_path, [answer('{"text": "a"}')] * 3, limit=2)
    assert c.correct(PNG).row and c.correct(PNG).row
    assert "2 lines" in c.correct(PNG).error and len(sent) == 2
    capped, sent = corrector(tmp_path / "x", [])
    capped.spend.add(5.0)
    assert capped.correct(PNG).error == ai_translate.capped(1.0) and sent == []


def test_a_new_evening_starts_counting_again(tmp_path):
    now = {"t": 1_795_700_000.0}
    c, _ = corrector(tmp_path, [answer('{"text": "a"}')] * 2, limit=1, clock=lambda: now["t"])
    assert c.correct(PNG).row
    now["t"] += 24 * 3600
    assert c.correct(PNG).row and c.sent_tonight == 1


def triggers(text, speaker="Pip", channel="match", **kw):
    args = {"readings_disagree": False, "wrapped": False, "known_names": ["pip", "pickle"],
            "edited_speakers": set(), "looks_german": lambda t: False} | kw  # fmt: skip
    return ai_correct.triggers(text, speaker, channel, **args)


def test_a_plain_line_of_a_known_name_isnt_sent():
    assert triggers("good game everyone") == set()


def test_each_trigger():
    assert triggers("gg wp", readings_disagree=True) == {"readings disagree"}
    assert "name near-miss" in triggers("good game", speaker="Picklle")
    assert "name near-miss" not in triggers("good game", speaker="Pickle")  # the name itself
    assert triggers("Thanks! ◇") == {"icon"}
    assert triggers("schöne grüße") == {"German"}
    assert triggers("ok") == {"very short"}
    assert triggers("a long line", wrapped=True) == {"wrapped"}
    assert triggers("good game", edited_speakers={"pip"}) == {"speaker edited lately"}


def test_system_lines_arent_short_or_german():
    assert triggers("You endorsed Jörg!", speaker=None, channel="system") == set()


def test_offline_isnt_asked_again_with_the_fallback_and_doesnt_count(tmp_path):
    offline = urllib.error.URLError("no route")
    c, sent = corrector(tmp_path, [offline])
    assert c.correct(PNG).error == ai_translate.OFFLINE and len(sent) == 1
    assert c.sent_tonight == 0  # the evening's limit is for lines OpenRouter saw


def test_a_timeout_counts_as_spent_and_the_fallback_gets_its_turn(tmp_path):
    c, sent = corrector(tmp_path, [TimeoutError("timed out"), answer('{"text": "[Pip]: hi"}', 0)])
    got = c.correct(PNG)
    assert got.row == "[Pip]: hi" and c.spend.used() == ai_correct.COST_GUESS[ai_correct.MODEL]
    assert sent[1]["max_tokens"] > 1000  # Sonnet's thinking doesn't eat the answer


def test_a_dropped_answer_doesnt_escape(tmp_path):
    import http.client

    c, _ = corrector(tmp_path, [http.client.IncompleteRead(b"{"), http.client.IncompleteRead(b"")])
    assert c.correct(PNG).error == ai_translate.OFFLINE


def test_an_icon_only_row_or_odd_icons_are_handled():
    import pytest

    with pytest.raises(ValueError):
        ai_correct.parse('{"text": "◇", "icons": []}')
    assert ai_correct.parse('{"text": "[Pip]: <3 ◇", "icons": "heart"}')[1] == ["heart"]
