"""Quick fixes on a chat line (#227): Edit and Delete on hover, Undo for 5 s.
Soft delete: the line stays in the database (deleted_at), every view reads around it. An edit
keeps the OCR reading (original_text) and becomes a hand-checked debug sample. With Translate
chat on, Translate shows a line's meaning under it (#468)."""

import html
import logging
import time
from collections.abc import Callable

from nicegui import run, ui

from yaptracker import config, runtime
from yaptracker.glyphs import GLYPH
from yaptracker.translate import FAILED, Translation
from yaptracker.ui.quick_verdict import OWN_CLICK

log = logging.getLogger(__name__)
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


# Pressing an Edit button doesn't take the focus from an open field: no blur-save before the
# click decides what to do (#241).
_KEEP_FOCUS = "(e) => e.preventDefault()"


def edit_button(line: ui.element, message_id: int, text: ui.element, mark: ui.element) -> None:
    """A small Edit at the line's right end: the text becomes a field, Enter saves, Esc cancels.
    While it's open the button says Cancel and closes it again (#241)."""
    with line:
        b = ui.element("button").classes("yt-line-act").mark("edit-line")
        b.props('type="button" title="Fix what I read"')
        with b:
            label = ui.label("Edit")
    b.on("mousedown", lambda: None, js_handler=_KEEP_FOCUS)
    b.on("click", lambda: toggle_edit(message_id, text, mark, label), js_handler=OWN_CLICK)


class _Editor:
    """The one open edit field of a window (#241)."""

    def __init__(self, message_id: int, text: ui.element, mark: ui.element, label: ui.element,
                 before) -> None:  # fmt: skip
        self.message_id, self.text, self.mark, self.label = message_id, text, mark, label
        self.before, self.open = before, True
        self.bar = getattr(ui.context.client, "yt_undo", None)  # kept: the field goes first
        parent = text.parent_slot.parent
        self.field = ui.input(value=before.text).props("dense borderless autofocus")
        self.field.classes("yt-line-edit").mark("edit-field")
        self.field.move(parent, target_index=parent.default_slot.children.index(text) + 1)
        text.classes(add="yt-hidden")
        label.set_text("Cancel")
        self.field.on("keydown.enter", lambda: self.finish(save=True))
        self.field.on("keydown.escape", lambda: self.finish(save=False))
        self.field.on("blur", lambda: self.finish(save=True))  # clicked away: kept, Undo covers it
        self.field.on("click", lambda: None, js_handler=_STAY)

    def finish(self, save: bool) -> None:
        if not self.open:  # Enter, then the blur of the removed field: once is enough
            return
        self.open = False
        value = " ".join((self.field.value or "").split())
        for element, change in ((self.field, "delete"), (self.text, "show"), (self.label, "edit")):
            if element.is_deleted:  # a new match cleared Live meanwhile
                continue
            if change == "delete":
                element.delete()
            elif change == "show":
                element.classes(remove="yt-hidden")
            else:
                element.set_text("Edit")
        if save and value and value != self.before.text and not self.text.is_deleted:
            _save_fix(self.before, value, self.text, self.mark, self.bar)


def toggle_edit(message_id: int, text: ui.element, mark: ui.element, label: ui.element) -> None:
    """One field at a time in a window: Edit on the open line closes it without saving, Edit on
    another line saves the open one (if changed) and opens the new one."""
    client = ui.context.client
    current = getattr(client, "yt_editing", None)
    client.yt_editing = None
    if current is not None and current.open:
        same = current.message_id == message_id and current.text is text
        current.finish(save=not same)
        if same:
            return
    store = runtime.store
    before = store.message(message_id) if store else None
    if before is not None:
        client.yt_editing = _Editor(message_id, text, mark, label, before)


def _save_fix(before, value: str, text: ui.element, mark: ui.element, bar) -> None:
    store = runtime.store
    store.edit_message(before.id, value, time.time())
    _show_text(text, value)
    show_mark(mark, True, before.original_text or before.text)
    if runtime.debug is not None:  # hand-checked OCR ground truth (#227)
        picture = runtime.pictures.path(before.id, before.ts) if runtime.pictures else None
        runtime.debug.correction(before, value, picture)

    def undo() -> None:
        store.unedit_message(before.id, before.text, before.edited_at)
        _show_text(text, before.text)
        show_mark(mark, before.edited_at is not None, before.original_text)

    if bar is not None:
        bar.show("Line fixed", undo)


def translate_button(line: ui.element, message, under: ui.element) -> Callable[[], None] | None:
    """A small Translate in `line`, only while Translate chat is on (#468). The
    translation, or what went wrong, appears dimmed in `under`: ↳ "gg, nice heals" (from
    Polish). Only the line's text goes to DeepL, off the UI thread; a failed one can be
    clicked again (in the same place), nothing retries by itself. Returns a check for a
    translation that came by itself (#469): Live calls it on every refresh."""
    if not config.translate_chat() or runtime.translator is None:
        return None
    if message.hero or message.channel == "system":  # the game's own words: nothing to translate
        return None
    with line:
        b = ui.element("button").classes("yt-line-act").mark("translate-line")
        b.props('type="button" title="What does it mean? Asks DeepL with your key"')
        with b:
            ui.label("Translate")
    shown: dict = {"out": None, "busy": False, "done": None}  # its one label

    def label() -> ui.element:
        if shown["out"] is None:
            with under:
                shown["out"] = ui.label().classes("yt-line-translation").mark("translation")
        return shown["out"]

    def show(done) -> None:
        out = label()
        shown["done"] = done
        if done.error:  # the same label, so a click again tries again in place
            out.set_text(f"\u21b3 {done.error}")
            out.classes(add="yt-line-translation--error")
        else:
            source = f" (from {done.source})" if done.source else ""
            out.set_text(f"\u21b3 \u201c{done.text}\u201d{source}")
            out.classes(remove="yt-line-translation--error")
            b.classes(add="yt-hidden")  # translated: nothing more to ask

    async def translate() -> None:
        if shown["busy"] or (shown["out"] is not None and shown["out"].is_deleted):
            return  # a click while asking, or a new match cleared Live meanwhile
        out = label()
        out.set_text("\u21b3 Translating\u2026")
        out.classes(remove="yt-line-translation--error")
        store = runtime.store
        now = store.message(message.id) if store is not None else None  # maybe fixed (#227)
        text = " ".join((now or message).text.replace(GLYPH, " ").split())
        shown["busy"] = True
        try:
            done = await run.io_bound(runtime.translator.translate, text)
        except Exception:  # never stuck on "Translating..."
            log.exception("translate: a line failed")
            done = Translation(error=FAILED)
        finally:
            shown["busy"] = False
        if not out.is_deleted:
            show(done)

    def came_by_itself() -> None:
        auto = runtime.auto_translate
        done = auto.known(message.id) if auto is not None else None
        had = shown["done"]
        if done is None or done == had or shown["busy"] or b.is_deleted:
            return
        if had is not None and not had.error:
            return  # translated already (clicked): an old error from the background stays out
        show(done)

    b.on("click", translate, js_handler=OWN_CLICK)
    came_by_itself()
    return came_by_itself


def delete_button(line: ui.element, ids: Callable[[], list[int]]) -> None:
    """A small Delete at the line's right end, shown on hover. `ids`: the messages it stands
    for (a callout shown once with ×4 is four)."""
    with line:
        b = ui.element("button").classes("yt-line-act yt-line-act--delete").mark("delete-line")
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
