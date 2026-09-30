"""Mouse logic for drawing, moving and resizing the chat box. No UI here, so it's easy to test."""

from dataclasses import dataclass

from yaptracker.capture.source import Region

MIN_SIZE = 40  # image px


@dataclass
class BoxEditor:
    image_width: int
    image_height: int
    region: Region
    grab: float = 30  # how close to a corner counts as grabbing it, in image px

    def __post_init__(self) -> None:
        self._mode: str | None = None
        self._anchor = (0.0, 0.0)  # fixed corner (resize/draw) or grab offset (move)

    @property
    def dragging(self) -> bool:
        return self._mode is not None

    def press(self, x: float, y: float) -> None:
        r = self.region
        corners = [(r.x, r.y), (r.x + r.width, r.y), (r.x, r.y + r.height),
                   (r.x + r.width, r.y + r.height)]  # fmt: skip
        for i, (cx, cy) in enumerate(corners):
            if abs(x - cx) <= self.grab and abs(y - cy) <= self.grab:
                self._mode, self._anchor = "resize", corners[3 - i]  # opposite corner stays put
                return
        if r.x <= x <= r.x + r.width and r.y <= y <= r.y + r.height:
            self._mode, self._anchor = "move", (x - r.x, y - r.y)
        else:
            self._mode, self._anchor = "draw", (x, y)

    def drag(self, x: float, y: float) -> None:
        x = min(max(x, 0), self.image_width)
        y = min(max(y, 0), self.image_height)
        if self._mode == "move":
            r = self.region
            nx = min(max(x - self._anchor[0], 0), self.image_width - r.width)
            ny = min(max(y - self._anchor[1], 0), self.image_height - r.height)
            self.region = Region(round(nx), round(ny), r.width, r.height)
        elif self._mode in ("resize", "draw"):
            ax, ay = self._anchor
            width, height = abs(x - ax), abs(y - ay)
            if width >= MIN_SIZE and height >= MIN_SIZE:
                self.region = Region(round(min(x, ax)), round(min(y, ay)), round(width),
                                     round(height))  # fmt: skip

    def release(self) -> None:
        self._mode = None
