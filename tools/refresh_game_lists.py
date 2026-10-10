"""Refresh src/yaptracker/data/game_lists.json from the OverFast API (#276). Build time only.

    python tools/refresh_game_lists.py

Fetches Overwatch 2's heroes and maps (en-us and de-de) from https://overfast-api.tekrop.fr/
(open source: https://github.com/TeKrop/overfast-api) and writes them, with the hand-written
queue names the API doesn't have, into the JSON the app reads. The app itself never goes online
for this (CLAUDE.md: local-only); run this by hand when a new hero or map ships, then commit.
"""

import json
import re
import time
import urllib.request
from pathlib import Path

API = "https://overfast-api.tekrop.fr"
OUT = Path(__file__).resolve().parents[1] / "src" / "yaptracker" / "data" / "game_lists.json"
LOCALES = ("en-us", "de-de")
# The queue names on the hero-select screen ("UNRANKED  ATTACK"); the API's "gamemodes" are
# map types (Escort, Control...). English and the German client's words.
QUEUES = ["UNRANKED", "COMPETITIVE", "QUICK PLAY", "ARCADE", "CUSTOM GAME", "PRACTICE",
          "STADIUM", "MYSTERY HEROES", "NO LIMITS", "TOTAL MAYHEM", "DEATHMATCH",
          "TEAM DEATHMATCH", "CAPTURE THE FLAG", "UNGEWERTET", "GEWERTET", "SCHNELLES SPIEL",
          "BENUTZERDEFINIERTES SPIEL", "TRAINING", "STADION"]  # fmt: skip
# Kept even if the API drops or lacks them (a hero or map the game still shows).
FALLBACK = {
    "heroes": ["Soldier: 76", "Torbjörn", "Wrecking Ball", "Lúcio"],
    "maps": ["Route 66", "King's Row", "Esperança", "Paraíso", "New Junk City", "Grímsvötn"],
}
# Map types the API doesn't have yet (#378): Grímsvötn shows the Escort truck in hero select.
FALLBACK_TYPES = {"Grímsvötn": ["escort"]}


def fetch(endpoint: str, locale: str) -> list[dict]:
    request = urllib.request.Request(f"{API}/{endpoint}?locale={locale}",
                                     headers={"User-Agent": "YapTracker build tools"})  # fmt: skip
    with urllib.request.urlopen(request, timeout=30) as response:
        items = json.load(response)
    for item in items:
        item["name"] = item["name"].replace("\u2019", "'")
    return items


def main() -> None:
    lists = {}
    map_types = dict(FALLBACK_TYPES)  # every map name, both languages -> its types (#364)
    for kind in ("heroes", "maps"):
        names = set(FALLBACK[kind])
        for locale in LOCALES:
            for item in fetch(kind, locale):
                names.add(item["name"])
                if kind == "maps" and item.get("gamemodes"):
                    map_types[item["name"]] = sorted(item["gamemodes"])
        lists[kind] = sorted(names, key=str.casefold)
    types = {name: map_types[name] for name in sorted(map_types, key=str.casefold)}
    data = {"source": f"{API} ({', '.join(LOCALES)}) + hand-written queue names (#276)",
            "fetched": time.strftime("%Y-%m-%d"), "queues": QUEUES, **lists,
            "map_types": types}  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    # a map's types on its own line: ["escort"], ["control", "flashpoint"]
    text = re.sub(r'\[\n\s+("[a-z-]+"(?:,\n\s+"[a-z-]+")*)\n\s+\]',
                  lambda m: "[" + re.sub(r",\n\s+", ", ", m[1]) + "]", text)  # fmt: skip
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"{OUT}: {len(lists['heroes'])} heroes, {len(lists['maps'])} maps, {len(QUEUES)} queues")


if __name__ == "__main__":
    main()
