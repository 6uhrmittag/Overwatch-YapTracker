"""Search all chat (#30): words, half words, filters, and fast on a big database."""

import random
import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell
from yaptracker.ui.search import _since, marked_html

NOW = time.time()
DAY = 86400


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def chat(store):
    """Three matches over two weeks; returns (NoodleBonk's id, the newest match)."""
    session = store.start_session(NOW - 14 * DAY)
    noodle = store.add_player("NoodleBonk", NOW - 14 * DAY)
    old = store.start_match(session, NOW - 14 * DAY, "heroselect", "push", "esperanca")
    store.add_message(ts=NOW - 14 * DAY, channel="match", text="that rein was cracked",
                      speaker_raw="NoodleBonk", player_id=noodle, match_id=old)  # fmt: skip
    mid = store.start_match(session, NOW - 3 * DAY, "gap")
    store.add_message(ts=NOW - 3 * DAY, channel="team", text="Reinhardt shatter on 3",
                      speaker_raw="zappy", match_id=mid)  # fmt: skip
    new = store.start_match(session, NOW - 60, "gap")
    store.add_message(ts=NOW - 60, channel="team", text="rein pls swap", speaker_raw="Marv",
                      role="me", match_id=new)  # fmt: skip
    store.add_message(ts=NOW - 30, channel="match", text="Lúcio wahoo", match_id=new,
                      speaker_raw="NoodleBonk", player_id=noodle)  # fmt: skip
    return noodle, new


def test_words_find_longer_words_newest_first_with_where(store):
    chat(store)
    hits = store.find("rein")
    assert [h.message.text for h in hits] == [
        "rein pls swap",
        "Reinhardt shatter on 3",
        "that rein was cracked",
    ]
    assert hits[1].marked == "\x01Reinhardt\x02 shatter on 3"
    assert (hits[2].match_number, hits[2].map) == (1, "esperanca")
    assert [h.message.text for h in store.find("lucio")] == ["Lúcio wahoo"]  # accents don't matter
    assert store.find('"; DROP TABLE chat_messages; --') == []  # words, never syntax


def test_filters_channel_player_and_time(store):
    noodle, _ = chat(store)
    assert [h.message.text for h in store.find("rein", channel="team")] == [
        "rein pls swap",
        "Reinhardt shatter on 3",
    ]
    assert [h.message.text for h in store.find("rein", player_ids=[noodle])] == [
        "that rein was cracked"
    ]
    assert [h.message.text for h in store.find("", player_ids=[noodle])] == [
        "Lúcio wahoo",
        "that rein was cracked",
    ]  # no words: everything they said
    assert len(store.find("rein", since=NOW - 7 * DAY)) == 2
    assert store.find("") == []  # nothing typed, no filter: nothing to show


def test_time_spans_start_at_midnight():
    now = time.mktime((2026, 10, 1, 22, 30, 0, 0, 0, -1))
    assert _since("any", now) is None
    assert time.localtime(_since("today", now))[:5] == (2026, 10, 1, 0, 0)
    assert time.localtime(_since("week", now))[:3] == (2026, 9, 25)


def test_highlights_are_escaped():
    assert (
        marked_html("<b>\x01rein\x02</b>") == '&lt;b&gt;<mark class="yt-hit">rein</mark>&lt;/b&gt;'
    )


def test_fast_on_100k_messages(store):
    random.seed(30)
    words = ["gg", "rein", "ana", "lucio", "push", "group", "up", "heal", "pls", "nice",
             "wahoo", "swap", "tank", "dps", "lol", "ez"]  # fmt: skip
    session = store.start_session(NOW - 400 * DAY)
    matches = [store.start_match(session, NOW - (400 - n) * DAY, "gap") for n in range(400)]
    rows = [(random.choice(matches), NOW - random.random() * 400 * DAY,
             random.choice(["team", "match"]), f"player{random.randrange(5000)}",
             " ".join(random.choices(words, k=random.randint(2, 8))))
            for _ in range(100_000)]  # fmt: skip
    conn = store._conn
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO chat_messages (match_id, ts, channel, speaker_raw, text) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("COMMIT")
    for query, filters in [("gg", {}), ("rein swap", {"channel": "team"}), ("wah", {}),
                           ("player42", {}), ("heal", {"since": NOW - 30 * DAY})]:  # fmt: skip
        started = time.perf_counter()
        hits = store.find(query, **filters)
        took = time.perf_counter() - started
        assert hits and took < 0.2, (query, took)


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_search_view_and_open_the_match(user: User, store, monkeypatch):
    config.save_setup_state("done")
    noodle, new = chat(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-search").click()
    await user.should_see("Type a word, a name, or both.")
    user.find(marker="search-box").type("rein")
    await user.should_see("3 yaps")
    await user.should_see("you:")  # own line
    await user.should_see("Match 1 on Esperanca")
    user.find(marker="channel-team").click()
    await user.should_see("2 yaps")
    user.find(marker="channel-all").click()
    user.find(marker="search-who").type("noodel")  # fuzzy, like Yappers
    await user.should_see("1 yap")
    user.find(marker="span-week").click()
    await user.should_see("Nobody said that. Yet.")
    user.find(marker="span-any").click()
    user.find(marker="search-hit").click()
    await user.should_see("All matches")  # the transcript of that match
    await user.should_see("that rein was cracked")
