"""From a sketch or photo to resin sheets: color quantization and contour tracing.

1. The image is reduced so its longest side is at most 1200 px.
2. k-means groups the pixels in CIELAB (perceptual distances, unlike RGB)
   into ``colors`` clusters; each cluster becomes one layer (one sheet color).
3. The cluster that covers more than 45 % of the image and touches its border
   is taken as the background (the paper, the wood) and ignored.
4. For each color: the mask is cleaned with a morphological opening (removes
   specks and one-pixel bridges), split into connected regions, and the
   outline of each region is traced (marching squares, ``find_contours``) and
   simplified with Douglas-Peucker (``approximate_polygon``). ``detail`` sets
   the tolerance: 1 keeps almost every pixel step, 0 gives few, smooth points.
5. Outlines are scaled to the requested size in millimeters and returned as
   ``path`` pieces centered on their own box. Regions smaller than ``minArea``
   mm² are discarded (a bisturí cannot cut them anyway).

Limitations: holes are filled (a ring becomes a disc). This matches how
barniz is built, where a later, upper layer covers the lower one, but a hole
that shows the background is lost. Gradients and shadows become bands of
flat color. It is classic image processing, not a generative model: the same
image and settings always give the same pieces.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure, morphology
from skimage.color import lab2rgb, rgb2lab
from sklearn.cluster import KMeans

from patronlab.ai.colors import color_name, rgb_to_hex
from patronlab.ai.geometry import area
from patronlab.document import MAX_BARNIZ_SHAPES, MAX_POINTS

MAX_SIDE = 1200
BACKGROUND_SHARE = 0.45
FIT_SAMPLE = 20_000  # pixels used to fit k-means; every pixel is then assigned


class ImageTooComplexError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__("IMAGE_TOO_COMPLEX")
        self.reason = reason


@dataclass(slots=True)
class VectorLayer:
    id: str
    name: str
    color: str
    area_share: float


@dataclass(slots=True)
class Vectorized:
    layers: list[VectorLayer]
    shapes: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)


def _tolerance(detail: float) -> float:
    """Douglas-Peucker tolerance in pixels: 0.5 px (detail 1) to 4 px (detail 0)."""
    return 0.5 + (1 - detail) * 3.5


def vectorize(
    image: Image.Image,
    width_mm: float,
    height_mm: float,
    colors: int = 4,
    detail: float = 0.5,
    min_area: float = 20.0,
    time_limit: float = 8.0,
) -> Vectorized:
    deadline = time.monotonic() + time_limit

    def check_time() -> None:
        if time.monotonic() > deadline:
            raise ImageTooComplexError(f"tardó más de {time_limit:.0f} s")

    notes: list[str] = []
    picture = image.convert("RGB")
    if max(picture.size) > MAX_SIDE:
        original = picture.size
        picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        notes.append(
            f"Imagen reducida de {original[0]}×{original[1]} a {picture.width}×{picture.height} px."
        )
    rgb = np.asarray(picture, dtype=np.float64) / 255
    rows, cols = rgb.shape[:2]
    lab = rgb2lab(rgb).reshape(-1, 3)

    # getcolors gives up (None) as soon as there are more distinct colors than asked.
    distinct = picture.getcolors(colors)
    k = colors if distinct is None else max(1, len(distinct))
    rng = np.random.default_rng(0)
    sample = lab[rng.choice(len(lab), size=min(FIT_SAMPLE, len(lab)), replace=False)]
    model = KMeans(n_clusters=k, n_init=3, random_state=0).fit(sample)
    labels = model.predict(lab).reshape(rows, cols)
    check_time()

    counts = np.bincount(labels.ravel(), minlength=k)
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    background = int(np.argmax(counts))
    if not (counts[background] / labels.size > BACKGROUND_SHARE and background in border):
        background = -1
    sx, sy = width_mm / cols, height_mm / rows
    tolerance = _tolerance(detail)
    radius = 1 if detail >= 0.5 else 2
    hexes = [
        rgb_to_hex(lab2rgb(center.reshape(1, 1, 3)).reshape(3)) for center in model.cluster_centers_
    ]
    notes.insert(0, f"{k} colores agrupados con k-means en CIELAB.")
    if background >= 0:
        notes.append(
            f"Fondo {hexes[background]} ({100 * counts[background] / labels.size:.0f} % de la "
            "imagen, toca los bordes) ignorado."
        )

    layers: list[VectorLayer] = []
    shapes: list[dict[str, Any]] = []
    discarded = 0
    used_names: dict[str, int] = {}
    # Biggest color first: the first sheet applied, at the bottom of the stack.
    for cluster in sorted((c for c in range(k) if c != background), key=lambda c: -counts[c]):
        mask = morphology.opening(labels == cluster, morphology.disk(radius))
        regions, _ = ndimage.label(mask)
        layer_id = f"l-{len(layers) + 1}"
        layer_shapes = []
        for index, box in enumerate(ndimage.find_objects(regions), start=1):
            check_time()
            if box is None:
                continue
            region = ndimage.binary_fill_holes(regions[box] == index)
            if region.sum() * sx * sy < min_area:
                discarded += 1
                continue
            padded = np.pad(region, 1).astype(np.float64)
            contour = max(measure.find_contours(padded, 0.5), key=len)
            simple = measure.approximate_polygon(contour, tolerance)[:-1]
            if len(simple) < 3:
                discarded += 1
                continue
            if len(simple) > MAX_POINTS:
                raise ImageTooComplexError(f"una forma tiene más de {MAX_POINTS} puntos")
            # Contour coordinates are pixel indices of the padded crop; +0.5 goes
            # from a pixel index to its center in continuous coordinates.
            points = [
                ((c - 1 + box[1].start + 0.5) * sx, (r - 1 + box[0].start + 0.5) * sy)
                for r, c in simple
            ]
            if area(points) < min_area:
                discarded += 1
                continue
            layer_shapes.append(points)
        if not layer_shapes:
            continue
        name = color_name(hexes[cluster]).capitalize()
        used_names[name] = used_names.get(name, 0) + 1
        if used_names[name] > 1:
            name = f"{name} {used_names[name]}"
        layers.append(
            VectorLayer(
                layer_id, name, hexes[cluster], round(float(counts[cluster] / labels.size), 4)
            )
        )
        for points in layer_shapes:
            xs = [x for x, _ in points]
            ys = [y for _, y in points]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            shapes.append(
                {
                    "id": f"v-{len(shapes) + 1}",
                    "kind": "path",
                    "x": round(cx, 2),
                    "y": round(cy, 2),
                    "width": round(max(xs) - min(xs), 3),
                    "height": round(max(ys) - min(ys), 3),
                    "rotation": 0,
                    "fill": hexes[cluster],
                    "stroke": "#2b2420",
                    "layerId": layer_id,
                    "groupId": None,
                    "points": [[round(x - cx, 2), round(y - cy, 2)] for x, y in points],
                }
            )
            if len(shapes) > MAX_BARNIZ_SHAPES:
                raise ImageTooComplexError(f"salen más de {MAX_BARNIZ_SHAPES} piezas")

    notes.append(
        f"{len(shapes)} contornos trazados y simplificados con Douglas-Peucker "
        f"(tolerancia {tolerance:.1f} px ≈ {tolerance * max(sx, sy):.2f} mm)."
    )
    if discarded:
        notes.append(f"Se descartaron {discarded} manchas menores de {min_area:g} mm².")
    notes.append("Los huecos de cada forma se rellenan: las capas de encima los cubren.")
    return Vectorized(layers, shapes, notes)
