"""Low-resolution rasterization used to score designs quickly.

Each shape becomes a boolean mask on a small grid; counting pixels gives
coverage, overlap and the visual center of mass without exact geometry.
"""

import numpy as np
from PIL import Image, ImageDraw

from patronlab.ai.geometry import outline
from patronlab.document import PatternDocument, Shape

GRID = 96  # cells on the longest side

MaskCache = dict[tuple, np.ndarray]


def _key(shape: Shape) -> tuple:
    # A path's points only change together with its size, so the size identifies them.
    return (
        shape.id,
        shape.kind,
        round(shape.x, 2),
        round(shape.y, 2),
        round(shape.width, 2),
        round(shape.height, 2),
        round(shape.rotation, 2),
    )


def shape_masks(
    document: PatternDocument, cache: MaskCache | None = None, grid: int = GRID
) -> np.ndarray:
    """Array of shape (shapes, rows, cols) with True where each shape covers a cell.

    With a cache, shapes that did not move are not drawn again (the evolutionary
    search changes only a few pieces from one candidate to the next).
    """
    scale = grid / max(document.width, document.height)
    cols = max(1, round(document.width * scale))
    rows = max(1, round(document.height * scale))
    masks = np.zeros((len(document.shapes), rows, cols), dtype=bool)
    for index, shape in enumerate(document.shapes):
        key = _key(shape) if cache is not None else None
        if cache is not None and key in cache:
            masks[index] = cache[key]
            continue
        image = Image.new("1", (cols, rows), 0)
        points = [(x * scale, y * scale) for x, y in outline(shape)]
        ImageDraw.Draw(image).polygon(points, fill=1)
        masks[index] = np.asarray(image, dtype=bool)
        if cache is not None:
            cache[key] = masks[index]
    return masks
