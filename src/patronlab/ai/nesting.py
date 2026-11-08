"""Material optimization: where to cut each piece, and in what order.

1. Nesting (2D bin packing, NP-hard): pieces are placed on a roll of fixed width
   with the skyline bottom-left heuristic. Each piece is tried at 0 and 90
   degrees and goes where its bottom ends lowest; pieces are processed from
   largest to smallest, the usual order that keeps the big ones from leaving
   gaps nobody can fill. Pieces are packed by their bounding box plus a cutting
   margin, so placements never overlap.
2. Cut order (a traveling salesman problem): the cutter (laser, blade or hand)
   should not wander. A nearest-neighbor tour is improved with 2-opt, which
   reverses segments while that shortens the route.

Both results are compared with a naive baseline so the gain is measurable:
pieces in drawing order, one shelf after another, no rotation; cut in drawing order.
"""

import math
from dataclasses import dataclass

from patronlab.ai.geometry import area, bounds, outline
from patronlab.document import PatternDocument


@dataclass(frozen=True, slots=True)
class Placement:
    shape_id: str
    x: float  # top-left corner of the piece's box on the material, mm
    y: float
    width: float
    height: float
    rotated: bool


@dataclass(frozen=True, slots=True)
class LayoutResult:
    placements: list[Placement]
    used_length: float
    waste_percent: float
    baseline_length: float
    baseline_waste_percent: float
    cut_order: list[str]
    cut_travel: float
    baseline_cut_travel: float


@dataclass(frozen=True, slots=True)
class _Piece:
    shape_id: str
    width: float
    height: float
    area: float


def _pieces(document: PatternDocument) -> list[_Piece]:
    pieces = []
    for shape in document.shapes:
        points = outline(shape)
        x0, y0, x1, y1 = bounds(points)
        pieces.append(_Piece(shape.id, x1 - x0, y1 - y0, area(points)))
    return pieces


def _skyline(pieces: list[_Piece], roll_width: float, spacing: float) -> list[Placement]:
    # The skyline: segments (x, width, top) describing the current upper edge.
    skyline = [(0.0, roll_width, 0.0)]
    placements = []
    for piece in sorted(pieces, key=lambda p: (max(p.width, p.height), p.area), reverse=True):
        best: tuple[float, float, float, float, float, bool] | None = None
        for rotated in (False, True):
            w = (piece.height if rotated else piece.width) + spacing
            h = (piece.width if rotated else piece.height) + spacing
            if w > roll_width + 1e-9:
                continue
            for start, _, _ in skyline:
                if start + w > roll_width + 1e-9:
                    continue
                # The piece rests on the highest segment it spans.
                top = max(
                    seg_top
                    for seg_x, seg_w, seg_top in skyline
                    if seg_x < start + w and seg_x + seg_w > start
                )
                candidate = (top + h, start, top, w, h, rotated)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
        if best is None:
            raise ValueError("PIECE_WIDER_THAN_MATERIAL")
        _, x, y, w, h, rotated = best
        placements.append(
            Placement(
                piece.shape_id,
                round(x, 2),
                round(y, 2),
                round(w - spacing, 2),
                round(h - spacing, 2),
                rotated,
            )
        )
        skyline = _raise(skyline, x, w, y + h)
    return placements


def _raise(
    skyline: list[tuple[float, float, float]], x: float, w: float, top: float
) -> list[tuple[float, float, float]]:
    result = []
    for seg_x, seg_w, seg_top in skyline:
        seg_end = seg_x + seg_w
        if seg_end <= x or seg_x >= x + w:
            result.append((seg_x, seg_w, seg_top))
            continue
        if seg_x < x:
            result.append((seg_x, x - seg_x, seg_top))
        if seg_end > x + w:
            result.append((x + w, seg_end - (x + w), seg_top))
    result.append((x, w, top))
    result.sort()
    # Merge neighbors at the same height so the skyline stays short.
    merged = [result[0]]
    for seg in result[1:]:
        last = merged[-1]
        if abs(last[2] - seg[2]) < 1e-9 and abs(last[0] + last[1] - seg[0]) < 1e-9:
            merged[-1] = (last[0], last[1] + seg[1], last[2])
        else:
            merged.append(seg)
    return merged


def _shelves(pieces: list[_Piece], roll_width: float, spacing: float) -> float:
    """Naive baseline: drawing order, left to right, a new row when one is full."""
    x = y = row = 0.0
    for piece in pieces:
        w, h = piece.width + spacing, piece.height + spacing
        if w > roll_width + 1e-9:
            raise ValueError("PIECE_WIDER_THAN_MATERIAL")
        if x + w > roll_width + 1e-9:
            x, y, row = 0.0, y + row, 0.0
        x += w
        row = max(row, h)
    return y + row


def _route_length(points: list[tuple[float, float]], order: list[int]) -> float:
    position = (0.0, 0.0)  # the cutter starts at the corner of the material
    total = 0.0
    for index in order:
        total += math.dist(position, points[index])
        position = points[index]
    return total


def _cut_order(points: list[tuple[float, float]]) -> list[int]:
    remaining = set(range(len(points)))
    order: list[int] = []
    position = (0.0, 0.0)
    while remaining:
        nearest = min(remaining, key=lambda i: (math.dist(position, points[i]), i))
        order.append(nearest)
        remaining.remove(nearest)
        position = points[nearest]
    # 2-opt on an open path that starts at the origin.
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                candidate = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                if _route_length(points, candidate) < _route_length(points, order) - 1e-9:
                    order = candidate
                    improved = True
    return order


def optimize_layout(
    document: PatternDocument, roll_width: float, spacing: float = 3.0
) -> LayoutResult:
    pieces = _pieces(document)
    if not pieces:
        raise ValueError("EMPTY_PATTERN")
    placements = _skyline(pieces, roll_width, spacing)
    used_length = max(p.y + p.height for p in placements)
    baseline_length = _shelves(pieces, roll_width, spacing)
    material = sum(piece.area for piece in pieces)

    def waste(length: float) -> float:
        return round(100 * (1 - material / (roll_width * length)), 1)

    by_id = {p.shape_id: p for p in placements}
    centers = [
        (
            by_id[piece.shape_id].x + by_id[piece.shape_id].width / 2,
            by_id[piece.shape_id].y + by_id[piece.shape_id].height / 2,
        )
        for piece in pieces
    ]
    order = _cut_order(centers)
    return LayoutResult(
        placements=placements,
        used_length=round(used_length, 1),
        waste_percent=waste(used_length),
        baseline_length=round(baseline_length, 1),
        baseline_waste_percent=waste(baseline_length),
        cut_order=[pieces[i].shape_id for i in order],
        cut_travel=round(_route_length(centers, order), 1),
        baseline_cut_travel=round(_route_length(centers, list(range(len(pieces)))), 1),
    )
