"""Multi-objective variations with NSGA-II (Deb et al., 2002).

A single weighted fitness hides trade-offs: a design can gain contrast and
lose balance, or save material by shrinking pieces and lose presence. NSGA-II
keeps the three objectives separate and returns the Pareto front: designs
where no objective can improve without another getting worse, so the
artisan picks the trade-off.

Objectives (all maximized):
  balance          visual center of mass close to the center (as in the GA)
  contrast         WCAG contrast of touching pieces and against the surface
  material saving  1 - length / original length, packing the pieces with the
                   fast SKYLINE nesting on a roll as wide as the design. It is
                   an estimate: pieces are packed by their boxes.

The genome (colors per layer or group, offsets per piece or group) is the
same as in the interactive evolution, so barniz layers keep one color and
radial groups keep their symmetry. Each generation, parents and children
(population 40 + 40) are sorted into non-dominated fronts; the next
population is filled front by front, breaking ties by crowding distance
(designs in less crowded parts of the front are preferred, which keeps the
front spread out). Reproducible with the same seed.
"""

import random
import time
from dataclasses import dataclass

from patronlab.ai.nesting import PieceCache, packed_length
from patronlab.ai.variations import Design, Evaluator, Genome, Weights
from patronlab.document import PatternDocument

POPULATION = 40
GENERATIONS = 25
MAX_POINTS = 12

Objectives = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ParetoPoint:
    document: PatternDocument
    balance: float
    contrast: float
    material_saving: float


def dominates(a: Objectives, b: Objectives) -> bool:
    return all(x >= y for x, y in zip(a, b, strict=True)) and a != b


def non_dominated_fronts(points: list[Objectives]) -> list[list[int]]:
    """Fast non-dominated sorting: indices grouped by front, best front first."""
    dominated_by: list[list[int]] = [[] for _ in points]
    counts = [0] * len(points)
    fronts: list[list[int]] = [[]]
    for i, p in enumerate(points):
        for j, q in enumerate(points):
            if dominates(p, q):
                dominated_by[i].append(j)
            elif dominates(q, p):
                counts[i] += 1
        if counts[i] == 0:
            fronts[0].append(i)
    while fronts[-1]:
        following = []
        for i in fronts[-1]:
            for j in dominated_by[i]:
                counts[j] -= 1
                if counts[j] == 0:
                    following.append(j)
        fronts.append(following)
    return fronts[:-1]


def crowding(points: list[Objectives], front: list[int]) -> dict[int, float]:
    """Crowding distance: how much room each design has around it on the front."""
    distance = {i: 0.0 for i in front}
    for objective in range(3):
        ordered = sorted(front, key=lambda i: points[i][objective])
        low, high = points[ordered[0]][objective], points[ordered[-1]][objective]
        if high - low < 1e-12:
            continue  # an objective where every design ties says nothing about room
        distance[ordered[0]] = distance[ordered[-1]] = float("inf")  # keep the extremes
        for k in range(1, len(ordered) - 1):
            gap = points[ordered[k + 1]][objective] - points[ordered[k - 1]][objective]
            distance[ordered[k]] += gap / (high - low)
    return distance


def _tournament(
    population: list[Genome], rank: dict[Genome, tuple[int, float]], rng: random.Random
) -> Genome:
    """Binary tournament: the lower front wins, then the one with more room around it."""
    a, b = rng.sample(population, 2)
    return min(a, b, key=lambda g: (rank[g][0], -rank[g][1]))


def pareto_variations(
    document: PatternDocument,
    palette: list[str],
    seed: int = 0,
    time_limit: float | None = None,
) -> list[ParetoPoint]:
    if not document.shapes:
        raise ValueError("EMPTY_PATTERN")
    if not palette:
        raise ValueError("EMPTY_PALETTE")
    deadline = time.monotonic() + time_limit if time_limit else None
    rng = random.Random(seed)
    design = Design(document)
    fitness = Evaluator(design, Weights().normalized())
    roll = document.width
    lengths: dict[tuple, float] = {}
    pieces: PieceCache = {}

    def length(genome: Genome) -> float:
        if genome.moves not in lengths:
            lengths[genome.moves] = packed_length(design.build(genome), roll, 3, pieces)
        return lengths[genome.moves]

    original_length = length(design.original)
    cache: dict[Genome, Objectives] = {}

    def objectives(genome: Genome) -> Objectives:
        if genome not in cache:
            score = fitness(genome)
            saving = 1 - length(genome) / original_length
            cache[genome] = (score.balance, score.contrast, round(saving, 4))
        return cache[genome]

    population = [design.original] + [
        design.mutate(design.original, palette, rng, 1.0) for _ in range(POPULATION - 1)
    ]
    rank: dict[Genome, tuple[int, float]] = {}

    def rank_all(genomes: list[Genome]) -> list[list[int]]:
        values = [objectives(g) for g in genomes]
        fronts = non_dominated_fronts(values)
        for level, front in enumerate(fronts):
            for i, room in crowding(values, front).items():
                rank[genomes[i]] = (level, room)
        return fronts

    rank_all(population)
    for generation in range(GENERATIONS):
        if deadline and time.monotonic() > deadline:
            break
        strength = 1.0 - 0.6 * generation / GENERATIONS
        children = []
        for _ in range(POPULATION):
            a, b = _tournament(population, rank, rng), _tournament(population, rank, rng)
            children.append(design.mutate(design.crossover(a, b, [], rng), palette, rng, strength))
        # Elitism (mu + lambda): parents and children compete for the next population.
        pool = list(dict.fromkeys(population + children))
        fronts = rank_all(pool)
        population = []
        for front in fronts:
            if len(population) + len(front) <= POPULATION:
                population.extend(pool[i] for i in front)
                continue
            by_room = sorted(front, key=lambda i: -rank[pool[i]][1])
            population.extend(pool[i] for i in by_room[: POPULATION - len(population)])
            break
        rank_all(population)

    # The final non-dominated front, one design per distinct objective vector.
    values = [objectives(g) for g in population]
    best = non_dominated_fronts(values)[0]
    distinct = list({values[i]: i for i in sorted(best)}.values())
    room = crowding(values, distinct)
    chosen = sorted(distinct, key=lambda i: (-room[i], values[i]))[:MAX_POINTS]
    chosen.sort(key=lambda i: values[i], reverse=True)
    return [
        ParetoPoint(design.build(population[i]), *(round(v, 4) for v in values[i])) for i in chosen
    ]
