"""Material optimization: where to cut each piece, and in what order.

1. Nesting (2D bin packing, NP-hard). Two heuristics, both "bottom-left"
   (each piece goes where it ends closest to the start of the material, then
   furthest left), pieces from largest to smallest:

   SKYLINE  packs the pieces' bounding boxes, each tried at 0 and 90 degrees.
            Fast and exact for rectangles, wasteful for leaves, stars, paths.
   RASTER   packs the real outlines: each piece is rasterized at 1 mm (grown
            by one pixel, so two pieces never really overlap), tried every 15
            degrees, and placed where it does not touch any placed piece or
            its cutting margin. Free positions are found with an FFT
            correlation on a 4 mm grid (conservative: a position free there is
            free at 1 mm) and then slid up and left at 1 mm.

   Material is a roll of fixed width, or sheets of a fixed size (barniz
   resin is stretched into sheets): a piece that does not fit on any sheet
   opens a new one, and sheets are counted. Per-layer nesting packs each
   layer (each resin color) on its own material.

2. Cut order (a traveling salesman problem): the cutter (laser, blade or
   bisturí) should not wander. A nearest-neighbor tour is improved with 2-opt,
   which reverses segments while that shortens the route.

Every result is compared with a naive baseline so the gain is measurable:
pieces in drawing order, one shelf after another, no rotation; cut in drawing
order. RASTER is also compared with SKYLINE.
"""

import math
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.signal import fftconvolve

from patronlab.ai.geometry import area, bounds, outline
from patronlab.document import PatternDocument, Shape

RASTER_STEP = 15  # degrees between the rotations RASTER tries
COARSE = 4  # millimeters per cell of the coarse search grid


@dataclass(frozen=True, slots=True)
class Placement:
    shape_id: str
    x: float  # top-left corner of the piece's box on the material, mm
    y: float
    width: float
    height: float
    rotated: bool
    angle: float = 0.0  # extra rotation applied on the material, degrees


@dataclass(frozen=True, slots=True)
class LayerPlan:
    layer_id: str
    color: str
    area_cm2: float
    used_length: float
    waste_percent: float
    sheets: int
    placements: list[Placement]


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
    method: str = "SKYLINE"
    skyline_length: float = 0.0
    skyline_waste_percent: float = 0.0
    layers: list[LayerPlan] | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Piece:
    shape: Shape
    width: float
    height: float
    area: float

    @property
    def shape_id(self) -> str:
        return self.shape.id


@dataclass(frozen=True, slots=True)
class Material:
    """A roll (height None: as long as needed) or sheets of a fixed size."""

    width: float
    height: float | None = None


PieceCache = dict[tuple, tuple[float, float, float]]


def _pieces(shapes: list[Shape], cache: PieceCache | None = None) -> list[_Piece]:
    """Box and real area of each piece; with a cache, unchanged pieces are not measured again."""
    pieces = []
    for shape in shapes:
        key = (shape.id, shape.kind, shape.width, shape.height, shape.rotation)
        if cache is not None and key in cache:
            width, height, piece_area = cache[key]
        else:
            points = outline(shape)
            x0, y0, x1, y1 = bounds(points)
            width, height, piece_area = x1 - x0, y1 - y0, area(points)
            if cache is not None:
                cache[key] = (width, height, piece_area)
        pieces.append(_Piece(shape, width, height, piece_area))
    return pieces


def _largest_first(pieces: list[_Piece]) -> list[_Piece]:
    return sorted(pieces, key=lambda p: (max(p.width, p.height), p.area), reverse=True)


# ---------- SKYLINE ----------


class _Skyline:
    def __init__(self, width: float, height: float | None) -> None:
        self.width, self.height = width, height
        # Segments (x, width, top) describing the current upper edge.
        self.segments = [(0.0, width, 0.0)]

    def best(self, piece: _Piece, spacing: float) -> tuple[float, float, float, float, bool] | None:
        """(bottom, x, y, w, h, rotated) of the best position, or None if it does not fit."""
        best = None
        segments = self.segments
        for rotated in (False, True):
            w = (piece.height if rotated else piece.width) + spacing
            h = (piece.width if rotated else piece.height) + spacing
            for k, (start, _, _) in enumerate(segments):
                end = start + w
                if end > self.width + 1e-9:
                    break  # segments are sorted by x: the next ones start further right
                # The piece rests on the highest segment it spans (they start at k).
                top, m = 0.0, k
                while m < len(segments) and segments[m][0] < end - 1e-9:
                    top = max(top, segments[m][2])
                    m += 1
                if best is not None and (top + h, start) >= best[:2]:
                    continue
                if self.height is not None and top + h - spacing > self.height + 1e-9:
                    continue
                best = (top + h, start, top, w, h, rotated)
        return best

    def place(self, x: float, w: float, top: float) -> None:
        self.segments = _raise(self.segments, x, w, top)


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


def _pack_skyline(
    pieces: list[_Piece], material: Material, spacing: float
) -> list[list[Placement]]:
    sheets: list[_Skyline] = []
    placed: list[list[Placement]] = []
    for piece in _largest_first(pieces):
        if min(piece.width, piece.height) > material.width + 1e-9:
            raise ValueError("PIECE_WIDER_THAN_MATERIAL")
        # First sheet where the piece fits; a new sheet if none (a roll has only one).
        found = next(
            ((i, spot) for i, s in enumerate(sheets) if (spot := s.best(piece, spacing))), None
        )
        if found is None:
            sheets.append(_Skyline(material.width + spacing, material.height))
            placed.append([])
            spot = sheets[-1].best(piece, spacing)
            if spot is None:
                raise ValueError("PIECE_LARGER_THAN_SHEET")
            found = (len(sheets) - 1, spot)
        index, (_, x, y, w, h, rotated) = found
        sheet = sheets[index]
        placed[index].append(
            Placement(
                piece.shape_id,
                round(x, 2),
                round(y, 2),
                round(w - spacing, 2),
                round(h - spacing, 2),
                rotated,
                90.0 if rotated else 0.0,
            )
        )
        sheet.place(x, w, y + h)
    return placed


# ---------- RASTER ----------


@dataclass(slots=True)
class _Footprint:
    mask: np.ndarray  # 1 mm cells the piece covers (grown by one cell)
    coarse: np.ndarray  # block-max of mask on the COARSE grid
    width: float  # real box of the rotated outline, mm
    height: float
    angle: float


def _footprint(shape: Shape, angle: float, margin: int) -> _Footprint:
    points = outline(shape, angle)
    x0, y0, x1, y1 = bounds(points)
    # One cell of slack on each side for the conservative growth.
    cols, rows = math.ceil(x1 - x0) + 3, math.ceil(y1 - y0) + 3
    image = Image.new("1", (cols, rows), 0)
    ImageDraw.Draw(image).polygon([(x - x0 + 1, y - y0 + 1) for x, y in points], fill=1)
    mask = ndimage.binary_dilation(np.asarray(image, dtype=bool), np.ones((3, 3), bool))
    pad_r, pad_c = (-rows) % COARSE, (-cols) % COARSE
    coarse = (
        np.pad(mask, ((0, pad_r), (0, pad_c)))
        .reshape((rows + pad_r) // COARSE, COARSE, (cols + pad_c) // COARSE, COARSE)
        .any(axis=(1, 3))
    )
    return _Footprint(mask, coarse, x1 - x0, y1 - y0, angle)


def _halo(mask: np.ndarray, margin: int) -> np.ndarray:
    """The mask grown by the cutting margin (a disc): what a placed piece blocks."""
    if not margin:
        return mask
    disk = np.hypot(*np.mgrid[-margin : margin + 1, -margin : margin + 1]) <= margin + 1e-9
    return ndimage.binary_dilation(np.pad(mask, margin), disk)


# Kinds whose outline looks the same after half a turn: 0-165 degrees are enough.
_HALF_TURN_SYMMETRIC = {"rect", "ellipse", "hexagon", "leaf"}


class _RasterSheet:
    def __init__(self, cols: int, height: int | None, margin: int) -> None:
        self.cols, self.height, self.margin = cols, height, margin
        self.coarse_cols = cols // COARSE
        self.fine = np.zeros((0, cols), dtype=bool)
        # Block-max of ``fine`` on the coarse grid, kept up to date by ``place``.
        self.coarse = np.zeros((0, self.coarse_cols), dtype=bool)
        self.used = 0  # rows from the start that hold a piece or its margin
        self._grow(height or 64)

    def _grow(self, rows: int) -> None:
        if rows > len(self.fine):
            extra = max(rows - len(self.fine), len(self.fine) // 2)
            extra += (-(len(self.fine) + extra)) % COARSE  # whole coarse rows
            self.fine = np.vstack([self.fine, np.zeros((extra, self.cols), dtype=bool)])
            self.coarse = np.vstack(
                [self.coarse, np.zeros((extra // COARSE, self.coarse_cols), dtype=bool)]
            )

    def _collides(self, mask: np.ndarray, x: int, y: int) -> bool:
        h, w = mask.shape
        return bool((self.fine[y : y + h, x : x + w] & mask).any())

    def best(self, foot: _Footprint) -> tuple[int, int] | None:
        h, w = foot.mask.shape
        if w > self.cols:
            return None
        limit = self.height if self.height is not None else self.used + h + COARSE
        if h > limit:
            return None
        self._grow(limit + COARSE)
        coarse_rows = math.ceil(limit / COARSE)
        coarse_cols = self.coarse_cols
        occupied = self.coarse[:coarse_rows]
        ch, cw = foot.coarse.shape
        candidates: list[tuple[int, int]] = []
        if ch <= coarse_rows and cw <= coarse_cols:
            hits = fftconvolve(
                occupied.astype(np.float32), foot.coarse[::-1, ::-1].astype(np.float32), "valid"
            )
            free = np.argwhere(hits < 0.5)  # row-major: lowest row first, then leftmost
            for cy, cx in free:
                x, y = int(cx) * COARSE, int(cy) * COARSE
                if x + w <= self.cols and y + h <= limit:
                    candidates.append((x, y))
                    break
        if not candidates and self.height is None:
            candidates.append((0, self.used))  # on a roll, the free end always fits
        if not candidates:
            return None
        x, y = candidates[0]
        # Slide up and left at 1 mm while nothing is in the way.
        moved = True
        while moved:
            moved = False
            while y > 0 and not self._collides(foot.mask, x, y - 1):
                y -= 1
                moved = True
            while x > 0 and not self._collides(foot.mask, x - 1, y):
                x -= 1
                moved = True
        return x, y

    def place(self, foot: _Footprint, x: int, y: int) -> None:
        h, w = foot.mask.shape
        m = self.margin
        halo = _halo(foot.mask, m)
        top, left = y - m, x - m
        r0, c0 = max(0, top), max(0, left)
        r1, c1 = top + halo.shape[0], min(self.cols, left + halo.shape[1])
        self._grow(r1)
        self.fine[r0:r1, c0:c1] |= halo[r0 - top : r1 - top, c0 - left : c1 - left]
        self.used = max(self.used, y + h + m)
        lo, hi = r0 // COARSE, math.ceil(r1 / COARSE)
        width = self.coarse_cols * COARSE
        self.coarse[lo:hi] = (
            self.fine[lo * COARSE : hi * COARSE, :width]
            .reshape(hi - lo, COARSE, self.coarse_cols, COARSE)
            .any(axis=(1, 3))
        )


def _pack_raster(
    pieces: list[_Piece], material: Material, spacing: float, deadline: float | None
) -> tuple[list[list[Placement]], list[str]]:
    margin = math.ceil(spacing)
    cols = math.floor(material.width) + 2  # the one-cell growth may touch both edges
    height = math.floor(material.height) + 2 if material.height is not None else None
    notes: list[str] = []
    all_angles = list(range(0, 360, RASTER_STEP))
    sheets: list[_RasterSheet] = []
    placed: list[list[Placement]] = []
    hurry = False
    for piece in _largest_first(pieces):
        if deadline and not hurry and time.monotonic() > deadline:
            hurry = True
            notes.append(
                "Se acabó el tiempo: las piezas restantes solo prueban 0°, 90°, 180°, 270°."
            )
        angles = [0, 90, 180, 270] if hurry else all_angles
        if piece.shape.kind in _HALF_TURN_SYMMETRIC:
            angles = [a for a in angles if a < 180]
        best = None
        for angle in angles:
            foot = _footprint(piece.shape, angle, margin)
            for index, sheet in enumerate(sheets):
                spot = sheet.best(foot)
                if spot is not None:
                    key = (index, spot[1] + foot.mask.shape[0], spot[0])
                    if best is None or key < best[0]:
                        best = (key, index, spot, foot)
                    break
        if best is None:
            sheet = _RasterSheet(cols, height, margin)
            for angle in angles:
                foot = _footprint(piece.shape, angle, margin)
                spot = sheet.best(foot)
                if spot is not None:
                    key = (len(sheets), spot[1] + foot.mask.shape[0], spot[0])
                    if best is None or key < best[0]:
                        best = (key, len(sheets), spot, foot)
            if best is None:
                if min(piece.width, piece.height) > material.width:
                    raise ValueError("PIECE_WIDER_THAN_MATERIAL")
                raise ValueError("PIECE_LARGER_THAN_SHEET")
            sheets.append(sheet)
            placed.append([])
        _, index, (x, y), foot = best
        sheets[index].place(foot, x, y)
        placed[index].append(
            Placement(
                piece.shape_id,
                # Grid cell 0 is -1 mm and the outline starts at cell 1 of its
                # mask, so the grid position is the outline's box in mm.
                float(x),
                float(y),
                round(foot.width, 2),
                round(foot.height, 2),
                foot.angle != 0,
                float(foot.angle),
            )
        )
    return placed, list(dict.fromkeys(notes))


# ---------- Shared ----------


def _shelves(pieces: list[_Piece], roll_width: float, spacing: float) -> float:
    """Naive baseline: drawing order, left to right, a new row when one is full."""
    x = y = row = 0.0
    for piece in pieces:
        w, h = piece.width + spacing, piece.height + spacing
        if w > roll_width + spacing + 1e-9:
            raise ValueError("PIECE_WIDER_THAN_MATERIAL")
        if x + w > roll_width + spacing + 1e-9:
            x, y, row = 0.0, y + row, 0.0
        x += w
        row = max(row, h)
    return y + row - spacing


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
    # 2-opt on an open path that starts at the origin. Reversing order[i..j] only
    # replaces two edges, so each move is evaluated in O(1).
    origin = (0.0, 0.0)
    improved, rounds = True, 0
    while improved and rounds < 50:
        improved, rounds = False, rounds + 1
        for i in range(len(order) - 1):
            before = points[order[i - 1]] if i else origin
            for j in range(i + 1, len(order)):
                first, last = points[order[i]], points[order[j]]
                after = points[order[j + 1]] if j + 1 < len(order) else None
                change = math.dist(before, last) - math.dist(before, first)
                if after is not None:
                    change += math.dist(first, after) - math.dist(last, after)
                if change < -1e-9:
                    order[i : j + 1] = order[i : j + 1][::-1]
                    improved = True
    return order


def _pack(
    pieces: list[_Piece],
    material: Material,
    spacing: float,
    method: str,
    deadline: float | None,
) -> tuple[list[Placement], int, float, list[str]]:
    """Placements (sheets stacked one after another), sheets used, used length, notes."""
    if method == "RASTER":
        sheets, notes = _pack_raster(pieces, material, spacing, deadline)
    else:
        sheets, notes = _pack_skyline(pieces, material, spacing), []
    if material.height is None:
        placements = sheets[0]
        return placements, 1, max(p.y + p.height for p in placements), notes
    placements = [
        Placement(
            p.shape_id,
            p.x,
            round(p.y + i * material.height, 2),
            p.width,
            p.height,
            p.rotated,
            p.angle,
        )
        for i, sheet in enumerate(sheets)
        for p in sheet
    ]
    last = max(p.y + p.height for p in sheets[-1])
    return placements, len(sheets), (len(sheets) - 1) * material.height + last, notes


def packed_length(
    document: PatternDocument,
    roll_width: float,
    spacing: float = 3.0,
    cache: PieceCache | None = None,
) -> float:
    """Only the SKYLINE length on a roll: the quick estimate used inside other searches."""
    pieces = _pieces(document.shapes, cache)
    if not pieces:
        return 0.0
    return _pack(pieces, Material(roll_width), spacing, "SKYLINE", None)[2]


def _waste(material_area: float, width: float, length: float) -> float:
    return round(100 * (1 - material_area / (width * length)), 1) if length > 0 else 0.0


def optimize_layout(
    document: PatternDocument,
    roll_width: float,
    spacing: float = 3.0,
    *,
    method: str = "SKYLINE",
    per_layer: bool = False,
    sheet: tuple[float, float] | None = None,
    time_limit: float | None = None,
) -> LayoutResult:
    pieces = _pieces(document.shapes)
    if not pieces:
        raise ValueError("EMPTY_PATTERN")
    deadline = time.monotonic() + time_limit if time_limit else None
    roll = Material(roll_width)
    placements, _, used_length, notes = _pack(pieces, roll, spacing, method, deadline)
    material = sum(piece.area for piece in pieces)
    baseline_length = _shelves(pieces, roll_width, spacing)
    if method == "RASTER":
        skyline = _pack(pieces, roll, spacing, "SKYLINE", None)[2]
    else:
        skyline = used_length

    layers = None
    if per_layer:
        sheet_material = Material(*sheet) if sheet else roll
        layer_color = {layer.id: layer.color for layer in document.layers}
        layers = []
        for layer_id, shapes in document.layer_shapes().items():
            layer_pieces = _pieces(shapes)
            layer_placements, sheets, length, layer_notes = _pack(
                layer_pieces, sheet_material, spacing, method, deadline
            )
            notes.extend(layer_notes)
            layer_area = sum(piece.area for piece in layer_pieces)
            available = (
                sheets * sheet_material.width * sheet_material.height
                if sheet_material.height is not None
                else sheet_material.width * length
            )
            layers.append(
                LayerPlan(
                    layer_id=layer_id or "",
                    color=layer_color.get(layer_id or "", shapes[0].fill),
                    area_cm2=round(layer_area / 100, 2),
                    used_length=round(length, 1),
                    waste_percent=round(100 * (1 - layer_area / available), 1),
                    sheets=sheets,
                    placements=layer_placements,
                )
            )

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
        waste_percent=_waste(material, roll_width, used_length),
        baseline_length=round(baseline_length, 1),
        baseline_waste_percent=_waste(material, roll_width, baseline_length),
        cut_order=[pieces[i].shape_id for i in order],
        cut_travel=round(_route_length(centers, order), 1),
        baseline_cut_travel=round(_route_length(centers, list(range(len(pieces)))), 1),
        method=method,
        skyline_length=round(skyline, 1),
        skyline_waste_percent=_waste(material, roll_width, skyline),
        layers=layers,
        notes=list(dict.fromkeys(notes)),
    )
