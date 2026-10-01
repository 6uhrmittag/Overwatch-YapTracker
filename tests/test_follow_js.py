"""Live follows new yaps (#166): the rules in static/follow.js, run in node.

Only you scrolling up stops following; new or taller lines never do. Scrolled up, new yaps show
the pill; the pill, scrolling back down or a new match bring following back.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config
from yaptracker.ui import shell

FOLLOW = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "follow.js"


def run(events: list[dict]) -> list[dict]:
    """The state after each event, starting where the page starts (following, at the bottom)."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = f"""
        const {{ ytFollowStep }} = require({json.dumps(str(FOLLOW))});
        let state = {{ on: true, pill: false, scroll: false }};
        const out = [];
        for (const event of {json.dumps(events)}) {{
            state = ytFollowStep(state, event);
            out.push(state);
        }}
        console.log(JSON.stringify(out));
    """
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_growing_content_never_stops_following():
    states = run([{"type": "grew"}] * 5)
    assert all(s["on"] and s["scroll"] and not s["pill"] for s in states)


def test_you_scrolling_up_stops_it_and_new_yaps_show_the_pill():
    up, grew, grew_again = run([{"type": "user-scroll", "atBottom": False}, {"type": "grew"},
                                {"type": "grew"}])  # fmt: skip
    assert not up["on"] and not up["pill"]
    assert not grew["scroll"] and grew["pill"] and grew_again["pill"]  # stays where you read


def test_pill_scrolling_down_or_a_new_match_bring_it_back():
    *_, pill = run([{"type": "user-scroll", "atBottom": False}, {"type": "grew"}, {"type": "pill"}])
    assert pill["on"] and pill["scroll"] and not pill["pill"]
    *_, down = run([{"type": "user-scroll", "atBottom": False}, {"type": "grew"},
                    {"type": "user-scroll", "atBottom": True}])  # fmt: skip
    assert down["on"] and not down["pill"]
    *_, cleared = run([{"type": "user-scroll", "atBottom": False}, {"type": "cleared"}])
    assert cleared["on"] and cleared["scroll"]


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_live_has_a_following_feed_and_the_pill(user: User):
    config.save_setup_state("done")
    await user.open("/")
    (feed,) = user.find(marker="feed").elements
    assert "yt-follow" in feed.classes  # what follow.js attaches to
    (pill,) = user.find(marker="new-yaps").elements
    assert "yt-hidden" in pill.classes
