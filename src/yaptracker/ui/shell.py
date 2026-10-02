"""App frame: logo, icon rail on the left, one content area."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nicegui import app, ui

from yaptracker import runtime
from yaptracker.ui import icons, search, sessions, views, yappers
from yaptracker.ui.quick_verdict import UndoBar

STATIC_DIR = Path(__file__).parent / "static"
STATIC_URL = "/static"


@dataclass(frozen=True)
class View:
    key: str
    label: str
    icon: str
    render: Callable[[], None]
    bottom: bool = False  # pinned to the bottom of the rail


VIEWS = [
    View("live", "Live", icons.LIVE, views.live),
    View("yappers", "Yappers", icons.YAPPERS, yappers.yappers),
    View("sessions", "Sessions", icons.SESSIONS, sessions.sessions),
    View("search", "Search", icons.SEARCH, search.search),
    View("settings", "Settings", icons.SETTINGS, views.settings, bottom=True),
]


def register_static_files() -> None:
    app.add_static_files(STATIC_URL, STATIC_DIR)


def _rail_button(view: View, on_click: Callable[[str], None]) -> ui.element:
    button = (
        ui.element("button")
        .classes("yt-rail-item")
        .props(f'type="button" aria-label="{view.label}" title="{view.label}"')
        .mark(f"nav-{view.key}")
        .on("click", lambda: on_click(view.key))
    )
    with button:
        ui.html(view.icon, sanitize=False)
    return button


def root() -> None:
    """Build the whole window for one client."""
    ui.add_head_html(f'<link rel="stylesheet" href="{STATIC_URL}/theme.css">')
    ui.add_head_html(f'<script defer src="{STATIC_URL}/follow.js"></script>')  # Live follows (#166)
    ui.add_head_html(f'<script defer src="{STATIC_URL}/copy.js"></script>')  # clean copies (#221)
    ui.colors(primary="#ff9c2a", dark="#12151c", dark_page="#0d1016")

    buttons: dict[str, ui.element] = {}

    current = {"view": None}

    def show(key: str, **kwargs) -> None:
        current["view"] = key
        for view_key, button in buttons.items():
            if view_key == key:
                button.classes(add="is-active").props('aria-current="page"')
            else:
                button.classes(remove="is-active").props(remove="aria-current")
        content.clear()
        with content:
            next(v for v in VIEWS if v.key == key).render(**kwargs)

    # Other views can switch views: a familiar-face card opens the profile (#26).
    ui.context.client.yt_show = show

    with ui.element("div").classes("yt-app"):
        with ui.element("nav").classes("yt-rail").props('aria-label="Main"'):
            with ui.element("div").classes("yt-logo").props('aria-label="YapTracker"'):
                ui.html(icons.LOGO, sanitize=False)
            for view in VIEWS:
                if not view.bottom:
                    buttons[view.key] = _rail_button(view, show)
            ui.element("div").classes("yt-rail-spacer")
            for view in VIEWS:
                if view.bottom:
                    buttons[view.key] = _rail_button(view, show)
        content = ui.element("main").classes("yt-main")
    ui.context.client.yt_undo = UndoBar()  # Saved + Undo after quick verdicts and notes (#220)

    show(VIEWS[0].key)

    # Paused must be visible from any view and from the taskbar (#20).
    title = {"paused": None}

    def update_title() -> None:
        paused = runtime.pause.paused
        if paused != title["paused"]:
            title["paused"] = paused
            ui.page_title("YapTracker - paused" if paused else "YapTracker")

    ui.timer(1.0, update_title)

    # Ctrl+Alt+F (#27): the hotkey brings the window forward; here Live opens with
    # "Who's that?" focused, from whichever view was open.
    lookup = {"handled": runtime.lookup_requested}

    def check_lookup() -> None:
        if runtime.lookup_requested == lookup["handled"]:
            return
        lookup["handled"] = runtime.lookup_requested
        if current["view"] != "live":
            show("live")
        focus = getattr(ui.context.client, "yt_focus_lookup", None)
        if focus is not None:
            focus()

    ui.timer(0.25, check_lookup)
