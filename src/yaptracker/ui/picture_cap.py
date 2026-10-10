"""Settings -> Your data: how much space line pictures may take (#389), 50 MB to 5 GB."""

import time

from nicegui import run, ui

from yaptracker import config, runtime
from yaptracker.ui.components import megabytes, size_label

STEPS_MB = (50, 100, 250, 500, 1000, 2000, 3000, 4000, 5000)
HINT = (
    "Pictures of each chat line, for emoji and for Read again. When the limit is reached, the "
    "oldest months go first."
)


def amount(mb: int) -> str:
    return f"{mb} MB" if mb < 1000 else f"{mb / 1000:g} GB"


def effect(mb: int) -> str:
    """What a limit of `mb` would delete, said before it does: "Frees 340 MB: ..."."""
    pictures = runtime.pictures
    if pictures is None or pictures.size_bytes() is None:
        return ""
    freed, kept = pictures.would_free(mb * 1_000_000)
    if not freed:
        return ""
    if kept is None:
        return f"Frees {megabytes(freed)}: all pictures go."
    month = time.strftime("%B %Y", time.strptime(kept, "%Y-%m"))
    return f"Frees {megabytes(freed)}: the pictures before {month} go."


def picture_cap() -> None:
    cap = config.picture_cap_mb()
    with ui.element("div").classes("yt-row yt-cap"):
        keep = ui.label(f"Keep up to {amount(cap)}").classes("yt-switch-label").mark("cap-label")
        slider = ui.slider(min=0, max=len(STEPS_MB) - 1, step=1,
                           value=STEPS_MB.index(cap) if cap in STEPS_MB else 5)  # fmt: skip
        slider.classes("yt-grow").props("markers snap").mark("pictures-cap")
    used, refill = size_label(
        lambda: runtime.pictures.size_bytes() if runtime.pictures else 0,
        lambda size: f"Line pictures: {size} of {amount(config.picture_cap_mb())}",
    )
    used.mark("pictures-size")
    said = ui.label().classes("yt-hint").mark("cap-effect")
    ui.label(HINT).classes("yt-hint")

    def chosen() -> int:
        return STEPS_MB[int(slider.value)]

    def preview() -> None:  # while dragging: nothing happens yet
        keep.set_text(f"Keep up to {amount(chosen())}")
        said.set_text(effect(chosen()))

    async def apply() -> None:  # on release
        mb = chosen()
        if mb == config.picture_cap_mb():
            return
        before = effect(mb)
        config.save_picture_cap_mb(mb)
        refill()
        if runtime.pictures is None:
            return
        runtime.pictures.set_cap(mb * 1_000_000)
        if before:  # lowered below what's there: the clean-up, in the background
            said.set_text(before.replace("Frees", "Freeing", 1))
            await run.io_bound(runtime.pictures.clean_up)
            said.set_text(before.replace("Frees", "Freed", 1).replace(" go.", " are gone."))
            refill()

    slider.on_value_change(preview)
    slider.on("change", apply)
