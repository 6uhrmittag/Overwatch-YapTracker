"""Yappers (#24): everyone you've met, with their verdict, when you last met and how much they
said. Search by name (fuzzy: "noodel" finds NoodleBonk), filter by verdict, sort."""

from collections.abc import Callable

from nicegui import ui
from rapidfuzz import fuzz

from yaptracker import config, runtime
from yaptracker.ui.components import VERDICTS, count, sticker, when
from yaptracker.ui.profile import profile
from yaptracker.ui.quick_verdict import quick_buttons, set_verdict

FOUND = 60  # rapidfuzz WRatio: typos and half names still find someone
_FILTERS = {"all": "Everyone", **{k: label for k, (label, _) in VERDICTS.items()},
            "none": "No verdict yet", "spicy": "Spicy yaps"}  # fmt: skip
_SORTS = {"last": "Last met", "times": "Times met"}


def matching(players: list, names: list[tuple[int, str]], query: str) -> list:
    """Players whose name or an alias is close to the query, best first."""
    query = query.strip().lower()
    if not query:
        return players
    best: dict[int, float] = {}
    for pid, name in names:
        score = max(fuzz.WRatio(query, name.lower()), 100 if query in name.lower() else 0)
        best[pid] = max(best.get(pid, 0), score)
    found = [p for p in players if best.get(p.id, 0) >= FOUND]
    return sorted(found, key=lambda p: -best[p.id])


def yappers(player_id: int | None = None) -> None:
    """The list; a click on someone opens their profile in its place (#25). With a player id
    (a familiar-face card, #26), their profile opens right away."""
    view = ui.element("div").classes("yt-view")

    def show_list() -> None:
        view.clear()
        with view:
            _list(open_profile)

    def open_profile(player_id: int) -> None:
        view.clear()
        with view:
            profile(player_id, on_back=show_list)

    if player_id is not None:
        open_profile(player_id)
    else:
        show_list()


def _list(open_profile: Callable[[int], None]) -> None:
    state = {"query": "", "filter": "all", "sort": "last"}
    with ui.element("header").classes("yt-header"):
        ui.label("Yappers").classes("yt-h1")
        met_count = ui.label().classes("yt-meta").mark("yapper-count")
        ui.element("div").classes("yt-grow")
        search = (
            ui.input(placeholder="Who's that? Type a name")
            .props("dense borderless clearable")
            .classes("yt-search")
            .mark("yapper-search")
        )
    with ui.element("div").classes("yt-row yt-filters"):
        filters = ui.element("div").classes("yt-seg").mark("yapper-filters")
        ui.element("div").classes("yt-grow")
        sorts = ui.element("div").classes("yt-seg").mark("yapper-sort")
    with ui.element("section").classes("yt-card yt-card--list"):
        body = ui.element("div").classes("yt-card-body").mark("yapper-list")

    def segment(container, options: dict, key: str) -> None:
        container.clear()
        with container:
            for value, label in options.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"{key}-{value}")
                if state[key] == value:
                    item.classes(add="is-active").props('aria-pressed="true"')
                with item:
                    ui.label(label)
                item.on("click", lambda value=value: choose(key, value))

    def choose(key: str, value: str) -> None:
        state[key] = value
        render()

    def render() -> None:
        segment(filters, _FILTERS, "filter")
        segment(sorts, _SORTS, "sort")
        store = runtime.store
        players = store.players() if store else []
        crew = config.identity()
        met_count.set_text(f"{len(players)} met" if players else "")
        body.clear()
        with body:
            if not players:
                ui.label("Nobody yet").classes("yt-h2")
                ui.label("Play a match and the people who yap will show up here.").classes(
                    "yt-hint"
                )
                return
            if state["filter"] == "none":
                players = [p for p in players if p.verdict is None]
            elif state["filter"] == "spicy":  # #77
                players = [p for p in players if p.spicy]
            elif state["filter"] != "all":
                players = [p for p in players if p.verdict == state["filter"]]
            if state["sort"] == "last":
                players.sort(key=lambda p: -(p.last_seen or 0))
            else:
                players.sort(key=lambda p: (-p.matches, -(p.last_seen or 0)))
            players = matching(players, store.player_names(), state["query"])
            if not players:
                ui.label(
                    "Never met them. Check the spelling, or they haven't typed in chat yet."
                    if state["query"]
                    else "Nobody with that verdict yet."
                ).classes("yt-hint").mark("yapper-none")
                return
            for player in players:
                row = ui.element("div").classes("yt-yapper").mark(f"yapper yapper-{player.id}")
                row.on("click", lambda pid=player.id: open_profile(pid))
                with row:
                    ui.label(player.display_name).classes("yt-yapper-name")
                    if player.verdict:
                        sticker(player.verdict)
                    if crew.role(player.display_name) == "crew":
                        ui.label("crew").classes("yt-crew-badge")
                    ui.element("div").classes("yt-grow")
                    matches = count(player.matches, "match", "matches")
                    yaps = count(player.yaps, "yap", "yaps")
                    met = when(player.last_seen)
                    ui.label(f"last met {met} \u00b7 {matches} \u00b7 {yaps}").classes("yt-meta")
                    if crew.role(player.display_name) is None:  # not you, not crew (#220)
                        pick = lambda v, pid=player.id: set_verdict(pid, v, render)  # noqa: E731
                        quick_buttons(player.verdict, pick)

    def on_search(e) -> None:
        state["query"] = e.value or ""
        render()

    search.on_value_change(on_search)
    render()
