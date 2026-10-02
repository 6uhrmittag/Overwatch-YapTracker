"""The channel icons of real chat lines (#228), as measured: Void's 1080p crops and Marv's 4K HDR
samples. Only the numbers are committed (tests/fixtures/channels/icons-real.json), no pictures
and no names."""

import json
from collections import Counter
from pathlib import Path

from yaptracker.channels import IconStats, classify_icon

ICONS = json.loads((Path(__file__).parent / "fixtures" / "channels" / "icons-real.json")
                   .read_text(encoding="utf-8"))["icons"]  # fmt: skip


def classified(source: str) -> Counter:
    return Counter((icon["truth"], classify_icon(IconStats(icon["blobs"], icon["width"],
                    icon["height"], icon["fill"], icon["middle"])))
                   for icon in ICONS if icon["source"] == source)  # fmt: skip


def test_voids_four_icons_all_right():
    right = {(c, c): 2 for c in ("team", "group", "system", "match")}
    assert classified("void-1080p") == Counter(right)


def test_marvs_4k_hdr_icons():
    seen = classified("marv-4k-hdr")
    assert seen[("system", "system")] == sum(n for (t, _), n in seen.items() if t == "system")
    # the small dot of "You ..." lines has no i: by shape it's a diamond, the text decides
    assert all(got == "match" for (t, got) in seen if t == "system-dot")
    assert all(got in ("group", "people") for (t, got) in seen if t == "group")
    team = sum(n for (t, _), n in seen.items() if t == "team")
    assert seen[("team", "team")] >= 0.85 * team  # the rest is blurred: colour and text decide
    assert not any(got in ("match", "system", "group") for (t, got) in seen if t == "team")
