"""Quick fixes on a chat line (#227): Edit and Delete on hover, Undo for 5 s.
Soft delete: the line stays in the database (deleted_at), every view reads around it. An edit
keeps the OCR reading (original_text) and becomes a hand-checked debug sample."""

import html
import time
from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.glyphs import GLYPH
from yaptracker.ui.quick_verdict import OWN_CLICK

_STAY = "(e) => e.stopPropagation()"  # typing in the field doesn't open the line's picture


def edited_mark(message) -> ui.element:
    """The small "edited" after a fixed line; its tooltip has what OCR read."""
    mark = ui.label("edited").classes("yt-line-edited").mark("edited-mark")
    show_mark(mark, message.edited_at is not None, message.original_text)
    return mark


def show_mark(mark: ui.element, on: bool, ocr: str | None) -> None:
    if on:
        mark.classes(remove="yt-hidden").props(f'title="{html.escape(f"Read as: {ocr}")}"')
    else:
        mark.classes(add="yt-hidden")


def _show_text(text: ui.element, value: str) -> None:
    if hasattr(text, "set_content"):  # ui.html: escaped, the ◇ as a chip (#128)
        chip = f'<span class="yt-glyph">{GLYPH}</span>'
        text.set_content(html.escape(value, quote=False).replace(GLYPH, chip))
    else:
        text.set_text(value)


def edit_button(line: ui.element, message_id: int, text: ui.element, mark: ui.element) -> None:
    """A small Edit at the line's right end: the text becomes a field, Enter saves, Esc cancels."""
    with line:
        b = ui.element("button").classes("yt-line-act").mark("edit-line")
        b.props('type="button" title="Fix what I read"')
        with b:
            ui.label("Edit")
    b.on("click", lambda: start_edit(message_id, text, mark), js_handler=OWN_CLICK)


def start_edit(message_id: int, text: ui.element, mark: ui.element) -> None:
    store, bar = runtime.store, getattr(ui.context.client, "yt_undo", None)
    before = store.message(message_id) if store else None
    if before is None:
        return
    parent = text.parent_slot.parent
    field = ui.input(value=before.text).props("dense borderless autofocus")
    field.classes("yt-line-edit").mark("edit-field")
    field.move(parent, target_index=parent.default_slot.children.index(text) + 1)
    text.classes(add="yt-hidden")

    def close() -> None:
        field.delete()
        text.classes(remove="yt-hidden")

    def save() -> None:
        value = " ".join((field.value or "").split())
        close()
        if not value or value == before.text:
            return
        store.edit_message(message_id, value, time.time())
        _show_text(text, value)
        show_mark(mark, True, before.original_text or before.text)
        if runtime.debug is not None:  # hand-checked OCR ground truth (#227)
            picture = runtime.pictures.path(before.id, before.ts) if runtime.pictures else None
            runtime.debug.correction(before, value, picture)

        def undo() -> None:
            store.unedit_message(message_id, before.text, before.edited_at)
            _show_text(text, before.text)
            show_mark(mark, before.edited_at is not None, before.original_text)

        if bar is not None:
            bar.show("Line fixed", undo)

    field.on("keydown.enter", save)
    field.on("keydown.escape", close)
    field.on("click", lambda: None, js_handler=_STAY)


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
