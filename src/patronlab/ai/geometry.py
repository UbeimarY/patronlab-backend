"""Shape outlines as polygons. The Angular editor draws the same unit outlines,
so what the artisan sees, what is exported and what the algorithms measure agree."""

import math

from patronlab.document import Shape

Point = tuple[float, float]


def _unit_outline(kind: str) -> list[Point]:
    """Outline inside the unit square centered at the origin ([-0.5, 0.5])."""
    if kind == "rect":
        return [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
    if kind == "ellipse":
        return [
            (0.5 * math.cos(2 * math.pi * i / 48), 0.5 * math.sin(2 * math.pi * i / 48))
            for i in range(48)
        ]
    if kind == "triangle":
        return [(0.0, -0.5), (0.5, 0.5), (-0.5, 0.5)]
    if kind == "hexagon":
        return [
            (0.5 * math.cos(math.pi / 3 * i), 0.5 * math.sin(math.pi / 3 * i)) for i in range(6)
        ]
    if kind == "star":
        points = []
        for i in range(10):
            radius = 0.5 if i % 2 == 0 else 0.2
            angle = -math.pi / 2 + math.pi / 5 * i
            points.append((radius * math.cos(angle), radius * math.sin(angle)))
        return points
    if kind == "leaf":
        steps = 24
        right = [(0.5 * math.sin(math.pi * t / steps), -0.5 + t / steps) for t in range(steps + 1)]
        left = [(-x, y) for x, y in reversed(right[1:-1])]
        return right + left
    raise ValueError(f"Unknown shape kind: {kind}")


_UNIT = {
    kind: _unit_outline(kind) for kind in ("rect", "ellipse", "triangle", "hexagon", "star", "leaf")
}


def local_outline(shape: Shape) -> list[Point]:
    """The shape's polygon before rotation, relative to its center (millimeters)."""
    if shape.kind == "path":
        return list(shape.points or [])
    return [(ux * shape.width, uy * shape.height) for ux, uy in _UNIT[shape.kind]]


def outline(shape: Shape, rotation_offset: float = 0.0) -> list[Point]:
    """The shape's polygon in document coordinates (millimeters).

    Paths are rotated around their center and translated, like every other kind.
    """
    angle = math.radians(shape.rotation + rotation_offset)
    cos, sin = math.cos(angle), math.sin(angle)
    return [
        (shape.x + px * cos - py * sin, shape.y + px * sin + py * cos)
        for px, py in local_outline(shape)
    ]


def area(points: list[Point]) -> float:
    """Shoelace formula."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def bounds(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)
