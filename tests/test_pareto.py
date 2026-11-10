import pytest

from patronlab.ai.pareto import crowding, dominates, non_dominated_fronts, pareto_variations
from patronlab.document import PatternDocument
from tests.conftest import GraphQL, sample_document
from tests.test_evolution import PALETTE, flower_plate

pytestmark = pytest.mark.anyio


def test_dominance_and_fronts() -> None:
    assert dominates((1, 1, 1), (1, 0, 1)) and not dominates((1, 1, 1), (1, 1, 1))
    assert not dominates((1, 0, 0), (0, 1, 0))
    points = [(1, 0, 0), (0, 1, 0), (0.5, 0.5, 0), (0.4, 0.4, 0), (0, 0, 0)]
    assert non_dominated_fronts(points) == [[0, 1, 2], [3], [4]]
    room = crowding(points, [0, 1, 2])
    assert room[0] == room[1] == float("inf") and 0 < room[2] < float("inf")


def test_the_front_is_non_dominated_and_reproducible() -> None:
    document = PatternDocument.model_validate(sample_document(8))
    points = pareto_variations(document, PALETTE, seed=4)
    assert 2 <= len(points) <= 12
    values = [(p.balance, p.contrast, p.material_saving) for p in points]
    assert len(set(values)) == len(values)
    for a in values:
        assert not any(dominates(b, a) for b in values)
    assert pareto_variations(document, PALETTE, seed=4) == points
    # Some trade-off saves material compared with the original design.
    assert max(p.material_saving for p in points) > 0


def test_barniz_rules_hold_on_the_front() -> None:
    document = PatternDocument.model_validate(flower_plate())
    for point in pareto_variations(document, PALETTE, seed=1):
        colors = {layer.id: layer.color for layer in point.document.layers}
        assert all(s.fill == colors[s.layer_id] for s in point.document.shapes)


async def test_pareto_through_graphql(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    query = """mutation($doc: JSON!, $pal: [String!]!) { paretoVariations(document: $doc, palette: $pal) {
      points { document balance contrast materialSaving } elapsedMs } }"""
    result = (await gql(query, token, doc=sample_document(6), pal=PALETTE))["data"]
    assert 1 <= len(result["paretoVariations"]["points"]) <= 12
    bad = await gql(query, token, doc=sample_document(6), pal=["rojo"])
    assert bad["errors"][0]["extensions"]["code"] == "INVALID_PALETTE"
