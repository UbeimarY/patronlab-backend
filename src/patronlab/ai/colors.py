"""Color science for the editor: CIELAB, CIEDE2000 differences and Spanish names.

Colors are compared in CIELAB, a space designed so that equal distances look
roughly equally different to people (RGB is not). The difference between two
colors is ΔE2000 (CIEDE2000), the CIE's current formula: ΔE ≈ 1 is the
smallest difference most people notice, and below ~10 two resin sheets laid
side by side are hard to tell apart in a workshop's light.

Color names come from our own table (``NAMES``): common Colombian Spanish
names, with hex values chosen by the team by eye, plus the colors usually
seen in Barniz de Pasto work. It is not a standard: it names a color by its
nearest entry (ΔE2000), so the name is a helpful approximation.
"""

import math
import warnings
from dataclasses import dataclass

import numpy as np
from skimage.color import deltaE_ciede2000, lab2rgb, rgb2lab

from patronlab.ai.geometry import area, outline
from patronlab.ai.raster import shape_masks
from patronlab.ai.variations import touching
from patronlab.document import PatternDocument

ANALYSIS_GRID = 192  # finer than the evolution's grid: small pieces must not miss a neighbor

# Our own table (see the module docstring). Order does not matter.
NAMES: dict[str, str] = {
    "#000000": "negro",
    "#1b1512": "negro esmalte",
    "#3b3b3b": "gris carbón",
    "#808080": "gris",
    "#c0c0c0": "gris plata",
    "#ffffff": "blanco",
    "#f6efe3": "crudo",
    "#e8dcc4": "beige",
    "#c8a165": "ocre claro",
    "#d4af37": "dorado",
    "#b5523b": "terracota",
    "#7a2e1f": "rojo óxido",
    "#8b1a1a": "rojo vino",
    "#b3202a": "rojo carmín",
    "#e03c31": "rojo",
    "#ff7f50": "coral",
    "#f28c28": "naranja",
    "#f4c430": "amarillo azafrán",
    "#ffe135": "amarillo",
    "#fff3b0": "amarillo pálido",
    "#9cae5b": "verde pistacho",
    "#6b8e23": "verde oliva",
    "#3f6b3a": "verde hoja",
    "#2e8b57": "verde esmeralda",
    "#1e5631": "verde botella",
    "#7fd1b9": "verde menta",
    "#2a9d8f": "verde azulado",
    "#40e0d0": "turquesa",
    "#87ceeb": "azul cielo",
    "#1f5fa0": "azul cobalto",
    "#1d3557": "azul marino",
    "#191970": "azul noche",
    "#4b0082": "índigo",
    "#6a3d9a": "morado",
    "#b57edc": "lila",
    "#c2185b": "fucsia",
    "#f4a6c0": "rosado",
    "#6f4e37": "café",
    "#a0522d": "siena",
    "#deb887": "madera clara",
}

_NAME_HEXES = list(NAMES)


def hex_to_rgb(colors: list[str]) -> np.ndarray:
    """(n, 3) floats in [0, 1]."""
    return np.array(
        [[int(c[i : i + 2], 16) / 255 for i in (1, 3, 5)] for c in colors], dtype=np.float64
    ).reshape(-1, 3)


def rgb_to_hex(rgb: np.ndarray) -> str:
    r, g, b = (int(round(float(np.clip(v, 0, 1)) * 255)) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def to_lab(colors: list[str]) -> np.ndarray:
    """(n, 3) CIELAB values (D65)."""
    return rgb2lab(hex_to_rgb(colors).reshape(-1, 1, 3)).reshape(-1, 3)


def lab_to_hex(lab: np.ndarray) -> str:
    return rgb_to_hex(lab2rgb(np.asarray(lab, dtype=np.float64).reshape(1, 1, 3)).reshape(3))


def delta_e(a: str, b: str) -> float:
    lab = to_lab([a, b])
    return float(deltaE_ciede2000(lab[0], lab[1]))


_NAME_LAB = to_lab(_NAME_HEXES)


def color_name(hex_color: str) -> str:
    """Name of the nearest entry of our table by ΔE2000."""
    lab = to_lab([hex_color])[0]
    distances = deltaE_ciede2000(np.broadcast_to(lab, _NAME_LAB.shape), _NAME_LAB)
    return NAMES[_NAME_HEXES[int(np.argmin(distances))]]


# ---------- Analysis of a design ----------

TOO_SIMILAR = 10.0  # ΔE2000 below this: neighboring sheets are hard to tell apart


@dataclass(frozen=True, slots=True)
class ColorPair:
    a: str
    b: str
    delta_e: float
    too_similar: bool


@dataclass(frozen=True, slots=True)
class ColorAnalysis:
    pairs: list[ColorPair]
    names: list[tuple[str, str]]
    harmonies: list[list[str]]


def _lch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """LCh to hex, lowering the chroma until the color exists in sRGB (gamut mapping)."""
    for _ in range(30):
        lab = np.array([lightness, chroma * math.cos(hue), chroma * math.sin(hue)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # lab2rgb warns before clipping out-of-gamut colors
            candidate = lab_to_hex(lab)
        if float(deltaE_ciede2000(to_lab([candidate])[0], lab)) < 1.0:
            return candidate
        chroma *= 0.9
    return candidate


def harmonies(base: str) -> list[list[str]]:
    """Complementary, analogous (±30°) and triadic (±120°) hues in LCh, same L and C."""
    lightness, a, b = to_lab([base])[0]
    chroma, hue = math.hypot(a, b), math.atan2(b, a)

    def turn(degrees: float) -> str:
        return _lch_to_hex(lightness, chroma, hue + math.radians(degrees))

    return [
        [base, turn(180)],
        [turn(-30), base, turn(30)],
        [base, turn(120), turn(240)],
    ]


def analyze(document: PatternDocument) -> ColorAnalysis:
    """ΔE2000 between colors of pieces that touch, Spanish names, and harmonies.

    Harmonies start from the dominant color (largest total area of pieces).
    """
    shapes = document.shapes
    if not shapes:
        return ColorAnalysis([], [], [])
    near = touching(shape_masks(document, grid=ANALYSIS_GRID))
    seen: set[tuple[str, str]] = set()
    pairs = []
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            a, b = sorted((shapes[i].fill, shapes[j].fill))
            if a == b or not near[i, j] or (a, b) in seen:
                continue
            seen.add((a, b))
            difference = round(delta_e(a, b), 2)
            pairs.append(ColorPair(a, b, difference, difference < TOO_SIMILAR))
    pairs.sort(key=lambda pair: (pair.delta_e, pair.a, pair.b))

    used = list(
        dict.fromkeys([layer.color for layer in document.layers] + [s.fill for s in shapes])
    )
    names = [(color, color_name(color)) for color in used]

    coverage: dict[str, float] = {}
    for shape in shapes:
        coverage[shape.fill] = coverage.get(shape.fill, 0.0) + area(outline(shape))
    dominant = max(coverage, key=lambda color: (coverage[color], color))
    return ColorAnalysis(pairs, names, harmonies(dominant))
