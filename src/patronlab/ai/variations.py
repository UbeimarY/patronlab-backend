"""Design variations by evolutionary search (a genetic algorithm).

The artisan's pattern is the starting point. Each candidate ("genome") keeps
every shape but may change its color (always taken from the palette) and nudge
its position, size and rotation a little. A population of candidates evolves
for a few generations: the best ones survive, are crossed and mutated, and the
fitness function decides which designs are better.

Fitness rewards, in order of weight:
  balance   visual center of mass close to the center of the piece
  overlap   few areas where shapes pile on top of each other
  contrast  neighboring shapes, and shapes vs background, easy to tell apart
  coverage  covered area close to the original design (keeps its density)

It is a search guided by explicit design criteria, not a generative model:
results are reproducible with the same seed, and every score can be explained.
"""

import math
import random
from dataclasses import dataclass

import numpy as np

from patronlab.ai.raster import shape_masks
from patronlab.document import PatternDocument, Shape

WEIGHTS = {"balance": 0.3, "overlap": 0.25, "contrast": 0.3, "coverage": 0.15}
POPULATION = 24
GENERATIONS = 18
ELITE = 4


@dataclass(frozen=True, slots=True)
class Score:
    total: float
    balance: float
    overlap: float
    contrast: float
    coverage: float


@dataclass(frozen=True, slots=True)
class Variation:
    document: PatternDocument
    score: Score


def _luminance(hex_color: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(hex_color[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio, from 1 (identical) to 21 (black on white)."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def score(document: PatternDocument, target_coverage: float) -> Score:
    if not document.shapes:
        return Score(0, 0, 0, 0, 0)
    masks = shape_masks(document)
    stack = masks.sum(axis=0)
    covered = stack > 0
    rows, cols = covered.shape
    covered_cells = int(covered.sum())

    coverage_value = covered_cells / covered.size
    coverage = max(0.0, 1 - abs(coverage_value - target_coverage) / max(target_coverage, 0.05))

    overlap = 1 - float((stack > 1).sum()) / max(1, covered_cells)

    if covered_cells:
        ys, xs = np.nonzero(covered)
        dx = (xs.mean() + 0.5) / cols - 0.5
        dy = (ys.mean() + 0.5) / rows - 0.5
        balance = max(0.0, 1 - math.hypot(dx, dy) / 0.5)
    else:
        balance = 0.0

    contrast = _contrast_score(document, masks)
    total = (
        WEIGHTS["balance"] * balance
        + WEIGHTS["overlap"] * overlap
        + WEIGHTS["contrast"] * contrast
        + WEIGHTS["coverage"] * coverage
    )
    return Score(
        round(total, 4),
        round(balance, 4),
        round(overlap, 4),
        round(contrast, 4),
        round(coverage, 4),
    )


def _contrast_score(document: PatternDocument, masks: np.ndarray) -> float:
    """Average of: shapes vs background, and pairs of shapes that touch."""

    # A ratio of 3 is the WCAG minimum for large graphics: count it as fully legible.
    def legible(a: str, b: str) -> float:
        return min(1.0, (contrast_ratio(a, b) - 1) / 2)

    background = [legible(shape.fill, document.background) for shape in document.shapes]
    # Shapes "touch" when their masks, grown by one cell, intersect.
    grown = masks.copy()
    grown[:, 1:, :] |= masks[:, :-1, :]
    grown[:, :-1, :] |= masks[:, 1:, :]
    grown[:, :, 1:] |= masks[:, :, :-1]
    grown[:, :, :-1] |= masks[:, :, 1:]
    flat = grown.reshape(len(document.shapes), -1).astype(np.uint8)
    touching = (flat @ flat.T) > 0
    pairs = [
        legible(document.shapes[i].fill, document.shapes[j].fill)
        for i in range(len(document.shapes))
        for j in range(i + 1, len(document.shapes))
        if touching[i, j]
    ]
    parts = [float(np.mean(background))]
    if pairs:
        parts.append(float(np.mean(pairs)))
    return sum(parts) / len(parts)


def _mutate(
    shapes: list[Shape],
    palette: list[str],
    document: PatternDocument,
    rng: random.Random,
    strength: float,
) -> list[Shape]:
    result = []
    for shape in shapes:
        changes: dict[str, float | str] = {}
        if rng.random() < 0.35:
            changes["fill"] = rng.choice(palette)
        if rng.random() < 0.3:
            changes["x"] = min(
                document.width, max(0.0, shape.x + rng.gauss(0, document.width * 0.04 * strength))
            )
            changes["y"] = min(
                document.height, max(0.0, shape.y + rng.gauss(0, document.height * 0.04 * strength))
            )
        if rng.random() < 0.2:
            factor = min(1.25, max(0.8, rng.gauss(1, 0.08 * strength)))
            changes["width"] = shape.width * factor
            changes["height"] = shape.height * factor
        if rng.random() < 0.2:
            changes["rotation"] = (shape.rotation + rng.choice([-30, -15, 15, 30, 45, 90])) % 360
        result.append(shape.model_copy(update=changes) if changes else shape)
    return result


def _crossover(a: list[Shape], b: list[Shape], rng: random.Random) -> list[Shape]:
    """Uniform crossover: each shape comes from one parent or the other."""
    return [sa if rng.random() < 0.5 else sb for sa, sb in zip(a, b, strict=True)]


def _signature(shapes: list[Shape]) -> tuple:
    return tuple(
        (s.fill, round(s.x), round(s.y), round(s.width), round(s.rotation)) for s in shapes
    )


def generate_variations(
    document: PatternDocument, palette: list[str], count: int = 4, seed: int = 0
) -> tuple[Score, list[Variation]]:
    """Returns the original's score and the best distinct variations found."""
    if not document.shapes:
        raise ValueError("EMPTY_PATTERN")
    if not palette:
        raise ValueError("EMPTY_PALETTE")
    rng = random.Random(seed)
    target = float(shape_masks(document).any(axis=0).mean())
    original_score = score(document, target)

    def build(shapes: list[Shape]) -> PatternDocument:
        return document.model_copy(update={"shapes": shapes})

    population = [_mutate(document.shapes, palette, document, rng, 1.0) for _ in range(POPULATION)]
    cache: dict[tuple, Score] = {}

    def fitness(shapes: list[Shape]) -> Score:
        key = _signature(shapes)
        if key not in cache:
            cache[key] = score(build(shapes), target)
        return cache[key]

    for generation in range(GENERATIONS):
        ranked = sorted(population, key=lambda shapes: fitness(shapes).total, reverse=True)
        parents = ranked[: POPULATION // 2]
        strength = 1.0 - 0.6 * generation / GENERATIONS  # explore first, refine later
        children = ranked[:ELITE]
        while len(children) < POPULATION:
            # Tournament selection: the better of two random parents.
            a = max(rng.sample(parents, 2), key=lambda shapes: fitness(shapes).total)
            b = max(rng.sample(parents, 2), key=lambda shapes: fitness(shapes).total)
            children.append(_mutate(_crossover(a, b, rng), palette, document, rng, strength))
        population = children

    by_key = {_signature(shapes): shapes for shapes in population}
    # Best candidates of the final population, keeping only visually distinct ones.
    best: list[Variation] = []
    seen_colors: set[tuple[str, ...]] = set()
    pool = sorted(by_key.values(), key=lambda shapes: fitness(shapes).total, reverse=True)
    for shapes in pool:
        colors = tuple(shape.fill for shape in shapes)
        if colors in seen_colors:
            continue
        seen_colors.add(colors)
        best.append(Variation(build(shapes), fitness(shapes)))
        if len(best) == count:
            break
    return original_score, best
