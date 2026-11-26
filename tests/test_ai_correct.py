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


# --- storing the AI's reading and the worker (#637) ------------------------------------------
import numpy as np  # noqa: E402

from yaptracker.store.repo import Store  # noqa: E402


def stored(tmp_path, text="Thanks! ◇", speaker="Plp"):
    store = Store.open(tmp_path / "y.db", tmp_path / "b")
    message_id = store.add_message(ts=100.0, channel="match", speaker_raw=speaker, text=text)
    return store, message_id


def test_the_ai_reading_keeps_ocrs_and_a_hand_edit_wins(tmp_path):
    store, mid = stored(tmp_path)
    assert store.ai_correct_message(mid, text="Thanks! [icon:thumbs-up]", speaker_raw="Pip",
                                     has_glyphs=True, ts=101.0)  # fmt: skip
    m = store.message(mid)
    assert (m.text, m.speaker_raw, m.ai_corrected_at) == ("Thanks! [icon:thumbs-up]", "Pip", 101.0)
    assert (m.original_text, m.speaker_ocr) == ("Thanks! ◇", "Plp")
    store.update_message(mid, channel="match", text="Thanks!", speaker_raw="Plp")  # later OCR
    m = store.message(mid)
    assert (m.text, m.speaker_raw) == ("Thanks! [icon:thumbs-up]", "Pip")  # the AI's stays
    store.edit_message(mid, "thanks!!", 102.0)
    m = store.message(mid)
    assert m.text == "thanks!!" and m.edited_at == 102.0  # the hand edit wins
    store.update_message(mid, channel="match", text="Thanks!", speaker_raw="Plp")
    assert store.message(mid).speaker_raw == "Pip"  # the AI's name isn't lost to an edit
    assert not store.ai_correct_message(mid, text="x", speaker_raw="Pip", has_glyphs=False,
                                        ts=103.0)  # fmt: skip
    store.close()


def test_the_name_ocr_read_is_kept_only_when_the_ai_changed_it(tmp_path):
    store, mid = stored(tmp_path, text="gg ez", speaker="Pip")
    store.ai_correct_message(mid, text="gg ez!", speaker_raw="Pip", has_glyphs=False, ts=1.0)
    assert store.message(mid).speaker_ocr is None
    store.close()


class FakeCorrector:
    def __init__(self, row):
        self.row, self.sent = row, 0

    def correct(self, png):
        self.sent += 1
        return ai_correct.Correction(row=self.row, model=ai_correct.MODEL)


def worker(tmp_path, store, row, relinked=None, labels=None, saved=None, player=None):
    picture = tmp_path / "line.png"
    import cv2

    cv2.imwrite(str(picture), np.full((40, 400, 3), 20, np.uint8))
    return ai_correct.Worker(
        FakeCorrector(row), store, lambda mid, ts: picture,
        relink=lambda speaker, ts: (relinked.append(speaker), player)[1]
        if relinked is not None else player,
        saved=(saved.append if saved is not None else lambda mid: None),
        label=(labels.append if labels is not None else lambda entry: None),
    )  # fmt: skip


def test_the_worker_stores_a_different_reading_relinks_the_name_and_keeps_a_label(tmp_path):
    store, mid = stored(tmp_path, text="hello there", speaker="Plp")
    pip = store.add_player("Pip", 50.0)
    relinked, labels, saved = [], [], []
    w = worker(tmp_path, store, "[Pip]: hello there", relinked, labels, saved, player=pip)
    w.handle(ai_correct.Waiting(mid, 100.0, frozenset({"name near-miss"}), 0.0))
    m = store.message(mid)
    assert m.speaker_raw == "Pip" and m.player_id == pip and relinked == ["Pip"]
    assert saved == [mid] and labels[0]["ocr_speaker"] == "Plp" and labels[0]["source"] == "ai"
    assert w.counts == {"name near-miss": 1} and w.corrected == 1
    store.close()


def test_the_same_reading_changes_nothing(tmp_path):
    store, mid = stored(tmp_path, text="hello there", speaker="Pip")
    w = worker(tmp_path, store, "[Pip]: hello there")
    w.handle(ai_correct.Waiting(mid, 100.0, frozenset({"very short"}), 0.0))
    assert store.message(mid).ai_corrected_at is None and w.corrected == 0
    store.close()


def test_a_line_fixed_by_hand_is_never_sent(tmp_path):
    store, mid = stored(tmp_path, text="helo", speaker="Pip")
    store.edit_message(mid, "hello", 101.0)
    w = worker(tmp_path, store, "[Pip]: hullo")
    w.handle(ai_correct.Waiting(mid, 100.0, frozenset({"very short"}), 0.0))
    assert w._corrector.sent == 0 and store.message(mid).text == "hello"
    store.close()


def test_submit_waits_a_moment_and_ignores_lines_without_a_trigger(tmp_path):
    store, mid = stored(tmp_path)
    now = {"t": 0.0}
    w = ai_correct.Worker(FakeCorrector("x"), store, lambda m, t: None, relink=lambda s, t: None,
                          clock=lambda: now["t"])  # fmt: skip
    w.submit(mid, 100.0, set())
    w.submit(mid, 100.0, {"icon"})
    w.submit(mid, 100.0, {"icon"})  # once in the queue
    assert w._next() is None  # not yet: dedup may still improve the OCR reading
    now["t"] = ai_correct.DELAY_S
    assert w._next().message_id == mid and w._next() is None
    store.close()


def test_a_later_ocr_reading_keeps_the_ais_player_marks_and_icons(tmp_path):
    store, mid = stored(tmp_path, text="gg ◇", speaker="Plp")
    pip = store.add_player("Pip", 50.0)
    store.ai_correct_message(mid, text="gg [icon:thumbs-up]", speaker_raw="Pip", has_glyphs=True,
                             ts=101.0)  # fmt: skip
    store.set_message_player(mid, pip)
    store.set_not_foreign(mid, "EN", "EN")
    store.update_message(mid, channel="match", text="gg", speaker_raw="Plp", has_glyphs=False)
    m = store.message(mid)
    assert (m.player_id, m.has_glyphs, m.translation_from) == (pip, 1, "EN")
    store.close()


def test_undoing_a_hand_edit_of_an_ai_line_keeps_its_mark_and_ocrs_reading(tmp_path):
    store, mid = stored(tmp_path, text="helo", speaker="Pip")
    store.ai_correct_message(mid, text="hello", speaker_raw="Pip", has_glyphs=False, ts=101.0)
    before = store.message(mid)
    store.edit_message(mid, "hello!!", 102.0)
    store.unedit_message(mid, before.text, before.edited_at)
    m = store.message(mid)
    assert (m.text, m.original_text, m.ai_corrected_at) == ("hello", "helo", 101.0)
    store.update_message(mid, channel="match", text="helo", speaker_raw="Pip")
    assert store.message(mid).text == "hello"
    store.close()


def test_the_tidy_up_never_removes_an_ai_line(tmp_path):
    store = Store.open(tmp_path / "y.db", tmp_path / "b")
    match = store.start_match(store.start_session(90.0), 95.0, "heroselect")
    mid = store.add_message(ts=100.0, match_id=match, channel="match", speaker_raw="Plp",
                            text="helo")  # fmt: skip
    store.ai_correct_message(mid, text="x", speaker_raw="Pip", has_glyphs=False, ts=1.0)
    assert mid in store.hand_touched(match)
    store.close()


def test_switched_off_nothing_more_goes_out(tmp_path):
    store, mid = stored(tmp_path, text="hello there", speaker="Plp")
    on = {"v": True}
    w = worker(tmp_path, store, "[Pip]: hello there")
    w._enabled = lambda: on["v"]
    w.submit(mid, 100.0, {"icon"})
    on["v"] = False
    w._clock = lambda: 1e9
    assert w._next() is None and w._queue == []
    w.handle(ai_correct.Waiting(mid, 100.0, frozenset({"icon"}), 0.0))
    assert w._corrector.sent == 0
    store.close()


def test_when_the_name_doesnt_line_up_ocrs_reading_stays(tmp_path):
    store, mid = stored(tmp_path, text="helo", speaker="Plp")
    w = worker(tmp_path, store, "Pip: hello")  # no brackets: the parser finds no name
    w.handle(ai_correct.Waiting(mid, 100.0, frozenset({"very short"}), 0.0))
    m = store.message(mid)
    assert (m.speaker_raw, m.text, m.ai_corrected_at) == ("Plp", "helo", None)
    store.close()
