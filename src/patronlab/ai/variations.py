"""Design variations by evolutionary search (a genetic algorithm).

The artisan's pattern is the starting point. A candidate ("genome") has two
kinds of genes, applied on top of the original design:

  color genes   one palette color per *color unit*: a whole layer in barniz
                mode (every sheet of a layer is cut from the same resin), a
                whole radial group, or a single loose piece.
  motion genes  one offset per *motion unit*: a radial group moves as a whole
                (its copies keep their symmetry), a loose piece may also be
                scaled and rotated a little. Pieces bigger than a quarter of
                the design are the base (the plate, the cushion's front) and
                never move.

A population evolves for a few generations: the best survive (elitism), are
chosen by tournament, crossed (uniform crossover per gene) and mutated, with
mutations getting smaller over time (explore first, refine later).

Interactive evolution: the artisan's favorite variations seed the first
population and pull the crossover toward them (each gene has a small chance
of being copied from a favorite instead of a parent). The weights of the
fitness can also be changed. Fitness, from 0 to 1:

  balance   visual center of mass close to the center of the piece
  overlap   few areas where shapes pile on top of each other
  contrast  WCAG contrast between pieces that touch (of different color
            units) and between every piece and the background / base color
  coverage  covered area close to the original design (keeps its density)

It is a search guided by explicit design criteria, not a generative model:
results are reproducible with the same seed, and every score can be explained.
"""

import functools
import math
import random
import time
from dataclasses import dataclass

import numpy as np

from patronlab.ai.raster import MaskCache, shape_masks
from patronlab.document import PatternDocument, Shape

POPULATION = 24
GENERATIONS = 18
ELITE = 4
FAVORITE_PULL = 0.15  # chance that a gene is copied from a favorite in the crossover
COLOR_RATE = 0.35
ROTATIONS = (-30, -15, 15, 30, 45, 90)
SCALE_RANGE = (0.6, 1.6)


@dataclass(frozen=True, slots=True)
class Weights:
    balance: float = 0.3
    overlap: float = 0.25
    contrast: float = 0.3
    coverage: float = 0.15

    def normalized(self) -> "Weights":
        values = (self.balance, self.overlap, self.contrast, self.coverage)
        if any(v < 0 or not math.isfinite(v) for v in values) or sum(values) <= 0:
            raise ValueError("INVALID_WEIGHTS")
        total = sum(values)
        return Weights(*(v / total for v in values))


DEFAULT_WEIGHTS = Weights()


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


@dataclass(frozen=True, slots=True)
class GenerationStat:
    generation: int
    best: float
    average: float


@functools.lru_cache(maxsize=4096)
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


def touching(masks: np.ndarray) -> np.ndarray:
    """Boolean matrix: shapes whose masks, grown by one cell, intersect."""
    grown = masks.copy()
    grown[:, 1:, :] |= masks[:, :-1, :]
    grown[:, :-1, :] |= masks[:, 1:, :]
    grown[:, :, 1:] |= masks[:, :, :-1]
    grown[:, :, :-1] |= masks[:, :, 1:]
    flat = grown.reshape(len(masks), -1).astype(np.float32)
    return (flat @ flat.T) > 0


def surface_color(document: PatternDocument) -> str:
    """What the pieces are laid on: the object's base enamel in barniz, else the background."""
    return document.object.base_color if document.object else document.background


def score(
    document: PatternDocument,
    target_coverage: float,
    weights: Weights = DEFAULT_WEIGHTS,
    *,
    masks: np.ndarray | None = None,
    units: list[int] | None = None,
) -> Score:
    """Fitness of a design. ``units`` gives each shape's color unit: touching
    pieces of the same unit (same layer or group) are not compared."""
    if not document.shapes:
        return Score(0, 0, 0, 0, 0)
    if masks is None:
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

    contrast = _contrast_score(document, masks, units)
    total = (
        weights.balance * balance
        + weights.overlap * overlap
        + weights.contrast * contrast
        + weights.coverage * coverage
    )
    return Score(
        round(total, 4),
        round(balance, 4),
        round(overlap, 4),
        round(contrast, 4),
        round(coverage, 4),
    )


def _contrast_score(document: PatternDocument, masks: np.ndarray, units: list[int] | None) -> float:
    """Average of: shapes vs the surface, and pairs of shapes that touch."""

    # A ratio of 3 is the WCAG minimum for large graphics: count it as fully legible.
    def legible(a: str, b: str) -> float:
        return min(1.0, (contrast_ratio(a, b) - 1) / 2)

    surface = surface_color(document)
    shapes = document.shapes
    background = [legible(shape.fill, surface) for shape in shapes]
    near = touching(masks)
    pairs = [
        legible(shapes[i].fill, shapes[j].fill)
        for i in range(len(shapes))
        for j in range(i + 1, len(shapes))
        if near[i, j] and (units is None or units[i] != units[j])
    ]
    parts = [float(np.mean(background))]
    if pairs:
        parts.append(float(np.mean(pairs)))
    return sum(parts) / len(parts)


def _is_base(shape: Shape, document: PatternDocument) -> bool:
    return shape.width * shape.height > 0.25 * document.width * document.height


Move = tuple[float, float, float, float]  # dx, dy (mm), scale factor, extra rotation (degrees)
NO_MOVE: Move = (0.0, 0.0, 1.0, 0.0)


@dataclass(frozen=True, slots=True)
class Genome:
    colors: tuple[str, ...]
    moves: tuple[Move, ...]


class Design:
    """How a document is split into genes, and how a genome becomes a document."""

    def __init__(self, document: PatternDocument) -> None:
        self.document = document
        shapes = document.shapes
        barniz = document.mode == "barniz"
        layer_colors = {layer.id: layer.color for layer in document.layers}

        color_keys: dict[tuple[str, str], int] = {}
        self.unit_of: list[int] = []
        initial: list[str] = []
        for shape in shapes:
            if barniz and shape.layer_id is not None:
                key = ("layer", shape.layer_id)
            elif shape.group_id is not None:
                key = ("group", shape.group_id)
            else:
                key = ("shape", shape.id)
            if key not in color_keys:
                color_keys[key] = len(color_keys)
                initial.append(
                    layer_colors.get(key[1], shape.fill) if key[0] == "layer" else shape.fill
                )
            self.unit_of.append(color_keys[key])
        self.layer_unit = {key[1]: index for key, index in color_keys.items() if key[0] == "layer"}

        fixed_groups = {
            s.group_id for s in shapes if s.group_id is not None and _is_base(s, document)
        }
        motion_keys: dict[tuple[str, str], int] = {}
        self.motion_of: list[int] = []
        members: list[list[Shape]] = []
        for shape in shapes:
            if shape.group_id in fixed_groups or (
                shape.group_id is None and _is_base(shape, document)
            ):
                self.motion_of.append(-1)
                continue
            key = ("group", shape.group_id) if shape.group_id else ("shape", shape.id)
            if key not in motion_keys:
                motion_keys[key] = len(motion_keys)
                members.append([])
            members[motion_keys[key]].append(shape)
            self.motion_of.append(motion_keys[key])
        self.is_group = [key[0] == "group" for key in motion_keys]
        # Offsets that keep every member's center inside the design.
        self.bounds = [
            (
                -min(s.x for s in group),
                document.width - max(s.x for s in group),
                -min(s.y for s in group),
                document.height - max(s.y for s in group),
            )
            for group in members
        ]
        self.first_member = [group[0] for group in members]
        self.original = Genome(tuple(initial), tuple(NO_MOVE for _ in members))

    def build(self, genome: Genome) -> PatternDocument:
        shapes = []
        for index, shape in enumerate(self.document.shapes):
            changes: dict = {}
            color = genome.colors[self.unit_of[index]]
            if color != shape.fill:
                changes["fill"] = color
            unit = self.motion_of[index]
            if unit >= 0 and genome.moves[unit] != NO_MOVE:
                dx, dy, scale, turn = genome.moves[unit]
                changes["x"] = shape.x + dx
                changes["y"] = shape.y + dy
                if scale != 1.0:
                    changes["width"] = shape.width * scale
                    changes["height"] = shape.height * scale
                    if shape.points:
                        changes["points"] = [(x * scale, y * scale) for x, y in shape.points]
                if turn:
                    changes["rotation"] = (shape.rotation + turn) % 360
            shapes.append(shape.model_copy(update=changes) if changes else shape)
        update: dict = {"shapes": shapes}
        if self.layer_unit:
            update["layers"] = [
                layer.model_copy(update={"color": genome.colors[self.layer_unit[layer.id]]})
                if layer.id in self.layer_unit
                else layer
                for layer in self.document.layers
            ]
        return self.document.model_copy(update=update)

    def genome_of(self, favorite: PatternDocument) -> Genome | None:
        """The genes of a variation the artisan liked, if it comes from this design."""
        by_id = {shape.id: shape for shape in favorite.shapes}
        if set(by_id) != {shape.id for shape in self.document.shapes}:
            return None
        favorite_layers = {layer.id: layer.color for layer in favorite.layers}
        colors: list[str | None] = [None] * len(self.original.colors)
        for index, shape in enumerate(self.document.shapes):
            unit = self.unit_of[index]
            if colors[unit] is None:
                fill = by_id[shape.id].fill
                if shape.layer_id in self.layer_unit:
                    fill = favorite_layers.get(shape.layer_id, fill)
                colors[unit] = fill
        moves = []
        for unit, original in enumerate(self.first_member):
            liked = by_id[original.id]
            low_x, high_x, low_y, high_y = self.bounds[unit]
            dx = min(high_x, max(low_x, liked.x - original.x))
            dy = min(high_y, max(low_y, liked.y - original.y))
            if self.is_group[unit]:
                moves.append((dx, dy, 1.0, 0.0))
                continue
            scale = liked.width / original.width if original.width else 1.0
            scale = min(SCALE_RANGE[1], max(SCALE_RANGE[0], scale))
            turn = (liked.rotation - original.rotation) % 360
            moves.append((dx, dy, round(scale, 4), turn))
        return Genome(tuple(c or "#000000" for c in colors), tuple(moves))

    def mutate(
        self, genome: Genome, palette: list[str], rng: random.Random, strength: float
    ) -> Genome:
        colors = tuple(
            rng.choice(palette) if rng.random() < COLOR_RATE else color for color in genome.colors
        )
        width, height = self.document.width, self.document.height
        moves = []
        for unit, (dx, dy, scale, turn) in enumerate(genome.moves):
            low_x, high_x, low_y, high_y = self.bounds[unit]
            if rng.random() < 0.3:
                dx = min(high_x, max(low_x, dx + rng.gauss(0, width * 0.04 * strength)))
                dy = min(high_y, max(low_y, dy + rng.gauss(0, height * 0.04 * strength)))
            if not self.is_group[unit]:
                if rng.random() < 0.2:
                    factor = min(1.25, max(0.8, rng.gauss(1, 0.08 * strength)))
                    scale = min(SCALE_RANGE[1], max(SCALE_RANGE[0], scale * factor))
                if rng.random() < 0.2:
                    turn = (turn + rng.choice(ROTATIONS)) % 360
            moves.append((dx, dy, scale, turn))
        return Genome(colors, tuple(moves))

    @staticmethod
    def crossover(a: Genome, b: Genome, favorites: list[Genome], rng: random.Random) -> Genome:
        """Uniform crossover; each gene may instead be copied from a favorite."""

        def pick(index: int, field: str) -> object:
            if favorites and rng.random() < FAVORITE_PULL:
                return getattr(rng.choice(favorites), field)[index]
            return getattr(a if rng.random() < 0.5 else b, field)[index]

        return Genome(
            tuple(pick(i, "colors") for i in range(len(a.colors))),  # type: ignore[misc]
            tuple(pick(i, "moves") for i in range(len(a.moves))),  # type: ignore[misc]
        )


class Evaluator:
    """Fitness with caches: per genome, and per shape mask."""

    def __init__(self, design: Design, weights: Weights) -> None:
        self.design = design
        self.weights = weights
        self.masks: MaskCache = {}
        self.cache: dict[Genome, Score] = {}
        self.target = float(shape_masks(design.document, self.masks).any(axis=0).mean())

    def __call__(self, genome: Genome) -> Score:
        if genome not in self.cache:
            document = self.design.build(genome)
            self.cache[genome] = score(
                document,
                self.target,
                self.weights,
                masks=shape_masks(document, self.masks),
                units=self.design.unit_of,
            )
        return self.cache[genome]


def evolve(
    document: PatternDocument,
    palette: list[str],
    favorites: list[PatternDocument] | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
    seed: int = 0,
    count: int = 6,
    time_limit: float | None = None,
) -> tuple[Score, list[Variation], list[GenerationStat]]:
    """Returns the original's score, the best distinct variations and the history.

    ``history`` has the best and average fitness of every generation (0 is the
    first population). With a time limit, the search stops early and keeps
    what it found.
    """
    if not document.shapes:
        raise ValueError("EMPTY_PATTERN")
    if not palette:
        raise ValueError("EMPTY_PALETTE")
    weights = weights.normalized()
    deadline = time.monotonic() + time_limit if time_limit else None
    rng = random.Random(seed)
    design = Design(document)
    fitness = Evaluator(design, weights)
    original_score = score(
        document,
        fitness.target,
        weights,
        masks=shape_masks(document, fitness.masks),
        units=design.unit_of,
    )

    liked = [g for g in (design.genome_of(f) for f in favorites or []) if g is not None]
    population = list(liked[: POPULATION // 2])
    while len(population) < POPULATION:
        parent = liked[len(population) % len(liked)] if liked else design.original
        population.append(design.mutate(parent, palette, rng, 1.0))

    history: list[GenerationStat] = []
    for generation in range(GENERATIONS + 1):
        totals = [fitness(genome).total for genome in population]
        history.append(
            GenerationStat(generation, round(max(totals), 4), round(sum(totals) / len(totals), 4))
        )
        if generation == GENERATIONS or (deadline and time.monotonic() > deadline):
            break
        ranked = sorted(population, key=lambda genome: fitness(genome).total, reverse=True)
        parents = ranked[: POPULATION // 2]
        strength = 1.0 - 0.6 * generation / GENERATIONS
        children = ranked[:ELITE]
        while len(children) < POPULATION:
            # Tournament selection: the better of two random parents.
            a = max(rng.sample(parents, 2), key=lambda genome: fitness(genome).total)
            b = max(rng.sample(parents, 2), key=lambda genome: fitness(genome).total)
            child = design.crossover(a, b, liked, rng)
            children.append(design.mutate(child, palette, rng, strength))
        population = children

    # Best candidates of the final population, keeping only visually distinct ones.
    best: list[Variation] = []
    seen: set[tuple[str, ...]] = set()
    for genome in sorted(set(population), key=lambda g: (-fitness(g).total, g.colors, g.moves)):
        if genome.colors in seen:
            continue
        seen.add(genome.colors)
        best.append(Variation(design.build(genome), fitness(genome)))
        if len(best) == count:
            break
    return original_score, best, history


def generate_variations(
    document: PatternDocument, palette: list[str], count: int = 4, seed: int = 0
) -> tuple[Score, list[Variation]]:
    """The original (non-interactive) variations: no favorites, default weights."""
    original, variations, _ = evolve(document, palette, seed=seed, count=count)
    return original, variations
