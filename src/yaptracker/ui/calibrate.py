"""Settings -> Calibrate: drag a box around the chat on a screenshot (docs/ui/mockup/Setup).

While Overwatch is captured, the screenshot comes straight from the game window (#112).
"""

from collections.abc import Callable
from io import BytesIO

import numpy as np
from nicegui import background_tasks, events, run, ui
from PIL import Image

from yaptracker import config, demo, runtime
from yaptracker.capture.black import SAY as BLACK_SAY
from yaptracker.capture.black import is_black
from yaptracker.ui.box_editor import BoxEditor
from yaptracker.ui.components import button
from yaptracker.ui.read_preview import ReadPreview

# The screenshot shows ~900 px wide; overlay sizes are given in screen px and scaled by this.
_DISPLAY_WIDTH = 900


def _overlay(editor: BoxEditor) -> str:
    r, k = editor.region, editor.image_width / _DISPLAY_WIDTH
    handle = 14 * k
    corners = [(r.x, r.y), (r.x + r.width, r.y), (r.x, r.y + r.height),
               (r.x + r.width, r.y + r.height)]  # fmt: skip
    handles = "".join(
        f'<rect x="{cx - handle / 2}" y="{cy - handle / 2}" width="{handle}" height="{handle}" '
        f'rx="{4 * k}" fill="#ff9c2a" stroke="#12151c" stroke-width="{2 * k}"/>'
        for cx, cy in corners
    )
    label_x, label_y = r.x + r.width + 24 * k, r.y + r.height / 2
    return (
        f'<rect x="{r.x}" y="{r.y}" width="{r.width}" height="{r.height}" rx="{8 * k}" '
        f'fill="rgba(255,156,42,.12)" stroke="#ff9c2a" stroke-width="{3 * k}" '
        f'stroke-dasharray="{12 * k} {12 * k}" class="yt-ants" style="--yt-dash: {24 * k}px"/>'
        f"{handles}"
        f'<g transform="translate({label_x} {label_y}) rotate(-3)">'
        f'<rect x="0" y="{-22 * k}" width="{230 * k}" height="{44 * k}" rx="{12 * k}" '
        f'fill="#ff9c2a"/><text x="{14 * k}" y="{6 * k}" font-size="{15 * k}" font-weight="800" '
        f'fill="#12151c" font-family="Nunito Sans, sans-serif">&#8592; Chat lives here, right?'
        f"</text></g>"
    )


def calibrate(on_done: Callable[[bool], None], steps: Callable[[], None] | None = None) -> None:  # noqa: C901 - split up after v1 (#311)
    """on_done(saved) returns to where calibration was opened from; `steps` draws the setup
    wizard's progress in the header (#76)."""
    state: dict = {"image": None, "editor": None}
    watcher = runtime.watcher
    live = watcher is not None and watcher.state == "capturing"

    with ui.element("header").classes("yt-header"):
        with ui.element("div"):
            ui.label("Show me the chat box").classes("yt-h1")
            ui.label("Takes about 30 seconds, promise.").classes("yt-subtitle")
        ui.element("div").classes("yt-grow")
        if steps is not None:
            steps()
        button("Back", lambda: on_done(False), "quiet")

    with ui.element("div").classes("yt-columns"):
        shot = ui.element("div").classes("yt-shot").mark("screenshot")
        with ui.element("aside").classes("yt-aside"):
            with ui.element("div").classes("yt-aside-scroll"):  # buttons below always stay visible
                with (
                    ui.element("section").classes("yt-card"),
                    ui.element("div").classes("yt-card-body"),
                ):
                    ui.label("Drag a box around the chat").classes("yt-h2")
                    ui.label(
                        "Be generous - a bit too big is fine, I'll ignore the empty parts. "
                        "Too small and I'll miss the long yaps."
                    ).classes("yt-text-soft")
                    if live:
                        ui.label(
                            "This is Overwatch right now. Chat faded? Press Enter in the game, "
                            "then take a new one."
                        ).classes("yt-hint")
                preview = ReadPreview()
                if live:
                    button(
                        "Use a screenshot file", lambda: upload.run_method("pickFiles"), "quiet"
                    ).mark("use-file")
            with ui.element("div").classes("yt-actions"):
                upload = (
                    ui.upload(auto_upload=True, on_upload=lambda e: _load_upload(e))
                    .props('accept="image/*"')
                    .classes("yt-hidden")
                )
                if live:
                    button(
                        "Take a new one", lambda: background_tasks.create(take_screenshot())
                    ).mark("take-new")
                else:
                    button("Pick a screenshot file", lambda: upload.run_method("pickFiles")).mark(
                        "pick-file"
                    )
                save_button = button("Yep, that's the chat →", lambda: save(), "primary")
                save_button.mark("save")

    def refresh_crop() -> None:
        image, editor = state["image"], state["editor"]
        r = editor.region
        preview.show(
            image.crop((r.x, r.y, r.x + r.width, r.y + r.height)),
            f"{r.width} \u00d7 {r.height} px at {r.x}, {r.y}  \u00b7  "
            f"{image.width}\u00d7{image.height} screenshot",
        )

    def on_mouse(e: events.MouseEventArguments) -> None:
        editor = state["editor"]
        if e.type == "mousedown":
            editor.press(e.image_x, e.image_y)
        elif e.type == "mousemove" and editor.dragging and e.buttons:
            editor.drag(e.image_x, e.image_y)
        elif editor.dragging:  # mouseup, or the button was released outside the image
            editor.release()
            refresh_crop()
        e.sender.set_content(_overlay(editor))

    def show(image: Image.Image) -> None:
        region = config.chat_region(image.width, image.height)
        state["image"] = image
        state["editor"] = BoxEditor(image.width, image.height, region,
                                    grab=image.width / _DISPLAY_WIDTH * 16)  # fmt: skip
        shot.clear()
        with shot:
            ui.interactive_image(
                image,
                content=_overlay(state["editor"]),
                on_mouse=on_mouse,
                events=["mousedown", "mousemove", "mouseup"],
                sanitize=False,
            ).classes("yt-shot-image")
        refresh_crop()
        save_button.props(remove="disabled")

    async def take_screenshot() -> None:
        frame = await run.io_bound(watcher.snapshot)
        if is_black(frame):  # exclusive Fullscreen: not a picture to draw on (#217)
            if state["image"] is None:
                with shot:
                    ui.label(f"{BLACK_SAY} Or use a screenshot file.").classes("yt-hint").mark(
                        "black-snapshot"
                    )
            return
        if frame is None:  # minimised, or capture just broke
            if state["image"] is None:
                with shot:
                    ui.label(
                        "Overwatch didn't send a picture. Bring it up once, or use a screenshot "
                        "file."
                    ).classes("yt-hint")
            return
        show(Image.fromarray(np.ascontiguousarray(frame[:, :, ::-1])))

    async def _load_upload(e: events.UploadEventArguments) -> None:
        show(Image.open(BytesIO(await e.file.read())).convert("RGB"))
        upload.reset()

    def save() -> None:
        image, editor = state["image"], state["editor"]
        config.save_chat_region(image.width, image.height, editor.region)
        if preview.learned_colours:  # team/system colours are user settings: remember them
            config.save_channel_colours(preview.learned_colours)
        on_done(True)

    if live:
        save_button.props("disabled")
        background_tasks.create(take_screenshot(), name="calibration screenshot")
    elif demo.ENABLED:
        show(demo.screenshot())
    else:
        save_button.props("disabled")
        with shot:
            ui.label(
                "I can't see Overwatch right now (not running, minimised or in Fullscreen). "
                "Start it in Borderless Windowed and I'll take the picture myself, or pick a "
                "screenshot file."
            ).classes("yt-hint").mark("not-live")
