import math
from typing import Any

import pytest

from patronlab.ai.variations import Design, Evaluator, Weights, evolve
from patronlab.document import PatternDocument
from tests.conftest import GraphQL, sample_document

pytestmark = pytest.mark.anyio

PALETTE = ["#b3202a", "#1f5fa0", "#3f6b3a", "#f4c430"]


def flower_plate() -> dict[str, Any]:
    """Barniz plate: a radial flower of 6 petals (one group) and loose dots on 3 layers."""
    petals = [
        {
            "id": f"p{i}",
            "kind": "leaf",
            "x": 150 + 50 * math.sin(math.radians(60 * i)),
            "y": 150 - 50 * math.cos(math.radians(60 * i)),
            "width": 24,
            "height": 60,
            "rotation": 60 * i,
            "fill": "#b3202a",
            "stroke": "#2b2420",
            "layerId": "rojo",
            "groupId": "flor",
        }
        for i in range(6)
    ]
    dots = [
        {
            "id": f"d{i}",
            "kind": "ellipse",
            "x": 60 + 45 * i,
            "y": 250,
            "width": 18,
            "height": 18,
            "rotation": 0,
            "fill": "#1f5fa0" if i % 2 else "#3f6b3a",
            "stroke": "#2b2420",
            "layerId": "azul" if i % 2 else "verde",
            "groupId": None,
        }
        for i in range(5)
    ]
    return {
        "schemaVersion": 2,
        "mode": "barniz",
        "width": 300,
        "height": 300,
        "object": {"kind": "plate", "width": 300, "height": 300, "leaf": "gold"},
        "layers": [
            {"id": "verde", "name": "Verde", "color": "#3f6b3a"},
            {"id": "rojo", "name": "Rojo", "color": "#b3202a"},
            {"id": "azul", "name": "Azul", "color": "#1f5fa0"},
        ],
        "groups": [{"id": "flor", "kind": "radial", "count": 6, "sourceId": "p0"}],
        "shapes": petals + dots,
    }


def _offsets(document: PatternDocument, group: str) -> list[tuple[float, float, float]]:
    members = [s for s in document.shapes if s.group_id == group]
    first = members[0]
    return [(round(s.x - first.x, 6), round(s.y - first.y, 6), s.rotation) for s in members]


def test_barniz_recolors_whole_layers_and_moves_groups_as_a_whole() -> None:
    document = PatternDocument.model_validate(flower_plate())
    _, variations, _ = evolve(document, PALETTE, seed=3)
    assert variations
    for variation in variations:
        doc = variation.document
        layer_color = {layer.id: layer.color for layer in doc.layers}
        for shape in doc.shapes:
            assert shape.fill == layer_color[shape.layer_id]
        # The radial group keeps its symmetry: same offsets and rotations between copies.
        assert _offsets(doc, "flor") == _offsets(document, "flor")
        for original, shape in zip(document.shapes, doc.shapes, strict=True):
            if shape.group_id:
                assert (shape.width, shape.height) == (original.width, original.height)


def test_history_has_every_generation_and_the_best_never_gets_worse() -> None:
    document = PatternDocument.model_validate(sample_document(8))
    original, variations, history = evolve(document, PALETTE, seed=1)
    assert [h.generation for h in history] == list(range(19))
    bests = [h.best for h in history]
    assert bests == sorted(bests)  # elitism
    assert all(h.average <= h.best for h in history)
    assert variations[0].score.total == history[-1].best >= original.total


def test_weights_change_what_the_search_optimizes() -> None:
    document = PatternDocument.model_validate(sample_document(8))
    only_contrast = Weights(balance=0, overlap=0, contrast=1, coverage=0)
    original, variations, _ = evolve(document, PALETTE, weights=only_contrast, seed=1)
    best = variations[0].score
    assert best.total == pytest.approx(best.contrast, abs=1e-3)
    assert best.contrast > original.contrast
    with pytest.raises(ValueError, match="INVALID_WEIGHTS"):
        Weights(0, 0, 0, 0).normalized()
    with pytest.raises(ValueError, match="INVALID_WEIGHTS"):
        Weights(-1, 1, 1, 1).normalized()


def test_favorites_seed_the_search() -> None:
    document = PatternDocument.model_validate(flower_plate())
    design = Design(document)
    raw = flower_plate()
    for layer in raw["layers"]:
        layer["color"] = "#f4c430"
    for shape in raw["shapes"]:
        shape["fill"] = "#f4c430"
        if shape["groupId"]:
            shape["x"] += 10
    favorite = PatternDocument.model_validate(raw)
    genome = design.genome_of(favorite)
    assert genome is not None
    rebuilt = design.build(genome)
    assert {s.fill for s in rebuilt.shapes} == {"#f4c430"}
    assert rebuilt.shapes[0].x == pytest.approx(favorite.shapes[0].x)
    # A favorite from another design (other pieces) is ignored, not an error.
    assert design.genome_of(PatternDocument.model_validate(sample_document(3))) is None

    # Seeded with the favorite, the first generation is at least as good as it.
    favorite_fitness = Evaluator(design, Weights().normalized())(genome).total
    _, _, history = evolve(document, PALETTE, favorites=[favorite], seed=0)
    assert history[0].best >= favorite_fitness


def test_evolution_is_reproducible() -> None:
    document = PatternDocument.model_validate(flower_plate())
    first = evolve(document, PALETTE, seed=5)
    second = evolve(document, PALETTE, seed=5)
    assert first == second


EVOLVE = """
mutation($doc: JSON!, $pal: [String!]!, $fav: [JSON!], $w: WeightsInput) {
  evolveVariations(document: $doc, palette: $pal, favorites: $fav, weights: $w, seed: 2) {
    original { total } variations { document score { total } }
    history { generation best average } elapsedMs
  }
}
"""


async def test_evolve_through_graphql(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    body = await gql(EVOLVE, token, doc=flower_plate(), pal=PALETTE, fav=[], w={"contrast": 0.6})
    result = body["data"]["evolveVariations"]
    assert len(result["history"]) == 19 and result["variations"]
    liked = result["variations"][0]["document"]
    again = await gql(EVOLVE, token, doc=flower_plate(), pal=PALETTE, fav=[liked])
    assert again["data"]["evolveVariations"]["history"][0]["best"] >= (
        result["variations"][0]["score"]["total"] - 0.2
    )

    def code(response: dict[str, Any]) -> str:
        return str(response["errors"][0]["extensions"]["code"])

    zero = {"balance": 0, "overlap": 0, "contrast": 0, "coverage": 0}
    assert code(await gql(EVOLVE, token, doc=flower_plate(), pal=PALETTE, w=zero)) == (
        "INVALID_ARGUMENT"
    )
    too_many = await gql(EVOLVE, token, doc=flower_plate(), pal=PALETTE, fav=[liked] * 7)
    assert code(too_many) == "INVALID_ARGUMENT"
    broken = flower_plate()
    broken["shapes"][0]["layerId"] = "nope"
    assert code(await gql(EVOLVE, token, doc=broken, pal=PALETTE)) == "INVALID_DOCUMENT"
    assert code(await gql(EVOLVE, None, doc=flower_plate(), pal=PALETTE)) == "UNAUTHENTICATED"
