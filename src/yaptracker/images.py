"""Pictures to and from files, for any path (#459). OpenCV's imwrite/imread can't open a path
with characters outside the system code page on Windows (C:\\Users\\Jürgen\\...): they return
False/None instead of raising. Encoding in memory and writing the bytes with Python works for
every path. Use these instead of cv2.imwrite / cv2.imread (a test keeps it that way)."""

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np


def write(path: Path, image: np.ndarray, params: Sequence[int] = ()) -> None:
    """The format follows the suffix (.webp, .png, .jpg). Raises OSError when it can't."""
    ok, data = cv2.imencode(path.suffix, image, list(params))
    if not ok:
        raise OSError(f"couldn't encode {path.name}")
    path.write_bytes(data.tobytes())


def read(path: Path) -> np.ndarray | None:
    """The picture in BGR, or None when there is none (missing or not a picture)."""
    try:
        data = np.fromfile(path, np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
