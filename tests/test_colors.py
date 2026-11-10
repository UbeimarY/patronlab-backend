from typing import Any

import pytest

from patronlab.ai.colors import analyze, delta_e, harmonies, to_lab
from patronlab.document import PatternDocument
from patronlab.samples import hummingbird_plate
from tests.conftest import GraphQL

pytestmark = pytest.mark.anyio


def _square(id: str, x: float, fill: str) -> dict[str, Any]:
    return {"id": id, "kind": "rect", "x": x, "y": 50, "width": 40, "height": 40,
            "rotation": 0, "fill": fill}  # fmt: skip


def test_touching_pieces_with_close_colors_are_flagged() -> None:
    document = PatternDocument.model_validate(
        {
            "width": 200,
            "height": 100,
            "shapes": [
                _square("a", 30, "#b3202a"),
                _square("b", 70, "#a81d28"),  # touches a, nearly the same red
                _square("c", 170, "#1f5fa0"),  # far from everything
            ],
        }
    )
    result = analyze(document)
    assert len(result.pairs) == 1
    pair = result.pairs[0]
    assert (pair.a, pair.b) == ("#a81d28", "#b3202a")
    assert pair.delta_e < 10 and pair.too_similar
    assert dict(result.names)["#1f5fa0"] == "azul cobalto"


def test_distinct_neighbors_are_not_too_similar() -> None:
    result = analyze(PatternDocument.model_validate(hummingbird_plate()))
    assert result.pairs
    assert all(p.delta_e == pytest.approx(delta_e(p.a, p.b), abs=0.01) for p in result.pairs)
    assert [p.delta_e for p in result.pairs] == sorted(p.delta_e for p in result.pairs)
    assert {name for _, name in result.names} >= {"rojo carmín", "azul cobalto"}


def test_harmonies_turn_the_hue_in_lch() -> None:
    import math

    complementary, analogous, triadic = harmonies("#b3202a")
    assert complementary[0] == analogous[1] == triadic[0] == "#b3202a"
    assert len(complementary) == 2 and len(analogous) == 3 and len(triadic) == 3
    base_l, a, b = to_lab(["#b3202a"])[0]
    other_l, a2, b2 = to_lab([complementary[1]])[0]
    turn = math.degrees(math.atan2(b2, a2) - math.atan2(b, a)) % 360
    # Out-of-gamut colors lose chroma but keep their hue and lightness.
    assert turn == pytest.approx(180, abs=3)
    assert other_l == pytest.approx(base_l, abs=2)


def test_an_empty_design_has_nothing_to_analyze() -> None:
    result = analyze(PatternDocument.model_validate({"width": 10, "height": 10, "shapes": []}))
    assert (result.pairs, result.names, result.harmonies) == ([], [], [])


async def test_analyze_colors_through_graphql(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    query = """mutation($doc: JSON!) { analyzeColors(document: $doc) {
      pairs { a b deltaE tooSimilar } names { hex name } harmonies elapsedMs } }"""
    body = await gql(query, token, doc=hummingbird_plate())
    result = body["data"]["analyzeColors"]
    assert len(result["harmonies"]) == 3 and result["names"]
    assert (await gql(query, None, doc=hummingbird_plate()))["errors"][0]["extensions"][
        "code"
    ] == "UNAUTHENTICATED"
