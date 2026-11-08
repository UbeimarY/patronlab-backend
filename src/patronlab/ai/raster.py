"""Low-resolution rasterization used to score designs quickly.

Each shape becomes a boolean mask on a small grid; counting pixels gives
coverage, overlap and the visual center of mass without exact geometry.
"""

import numpy as np
from PIL import Image, ImageDraw

from patronlab.ai.geometry import outline
from patronlab.document import PatternDocument

GRID = 96  # cells on the longest side


def shape_masks(document: PatternDocument) -> np.ndarray:
    """Array of shape (shapes, rows, cols) with True where each shape covers a cell."""
    scale = GRID / max(document.width, document.height)
    cols = max(1, round(document.width * scale))
    rows = max(1, round(document.height * scale))
    masks = np.zeros((len(document.shapes), rows, cols), dtype=bool)
    for index, shape in enumerate(document.shapes):
        image = Image.new("1", (cols, rows), 0)
        points = [(x * scale, y * scale) for x, y in outline(shape)]
        ImageDraw.Draw(image).polygon(points, fill=1)
        masks[index] = np.asarray(image, dtype=bool)
    return masks
