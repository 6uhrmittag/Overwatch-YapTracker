"""Quick fixes on a chat line (#227): Delete on hover, gone everywhere at once, Undo for 5 s.
Soft delete: the line stays in the database (deleted_at), every view reads around it."""

import time
from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui.quick_verdict import OWN_CLICK


def delete_button(line: ui.element, ids: Callable[[], list[int]]) -> None:
    """A small Delete at the line's right end, shown on hover. `ids`: the messages it stands
    for (a callout shown once with ×4 is four)."""
    with line:
        b = ui.element("button").classes("yt-line-act").mark("delete-line")
        b.props('type="button" title="Delete this line (you can undo it)"')
        with b:
            ui.label("Delete")
    b.on("click", lambda: delete(line, ids()), js_handler=OWN_CLICK)


def delete(line: ui.element, ids: list[int]) -> None:
    store, bar = runtime.store, getattr(ui.context.client, "yt_undo", None)
    if store is None:
        return
    now = time.time()
    for message_id in ids:
        store.delete_message(message_id, now)
    line.classes(add="yt-hidden")

    def undo() -> None:
        for message_id in ids:
            store.restore_message(message_id)
        line.classes(remove="yt-hidden")

    if bar is not None:
        bar.show("Line deleted" if len(ids) == 1 else f"{len(ids)} lines deleted", undo)
