from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

from patronlab.ai.geometry import area, bounds, outline
from patronlab.ai.nesting import Placement, optimize_layout
from patronlab.document import PatternDocument
from tests.conftest import GraphQL
from tests.test_evolution import flower_plate

pytestmark = pytest.mark.anyio


def mixed_pieces(count: int = 24) -> PatternDocument:
    kinds = ["leaf", "star", "triangle"]
    return PatternDocument.model_validate(
        {
            "width": 300,
            "height": 300,
            "shapes": [
                {
                    "id": f"h{i}",
                    "kind": kinds[i % 3],
                    "x": 150,
                    "y": 150,
                    "width": 38 + i % 4 * 6,
                    "height": 80 - i % 5 * 8,
                    "rotation": 0,
                    "fill": "#3f6b3a",
                }
                for i in range(count)
            ],
        }
    )


def overlapping_cells(
    document: PatternDocument, placements: list[Placement], width: float, resolution: int = 4
) -> int:
    """Draws every placed outline at 0.25 mm and counts cells covered twice."""
    by_id = {s.id: s for s in document.shapes}
    length = max(p.y + p.height for p in placements)
    cover = np.zeros((int((length + 2) * resolution), int((width + 2) * resolution)), np.int16)
    for p in placements:
        points = outline(by_id[p.shape_id], p.angle)
        x0, y0, x1, y1 = bounds(points)
        # The box reported is the box of the rotated outline.
        assert (p.width, p.height) == pytest.approx((x1 - x0, y1 - y0), abs=0.01)
        placed = [(x - x0 + p.x, y - y0 + p.y) for x, y in points]
        assert min(x for x, _ in placed) >= -1e-6 and max(x for x, _ in placed) <= width + 1e-6
        image = Image.new("1", (cover.shape[1], cover.shape[0]))
        ImageDraw.Draw(image).polygon([(x * resolution, y * resolution) for x, y in placed], fill=1)
        cover += np.asarray(image)
    return int((cover > 1).sum())


def test_raster_never_overlaps_real_outlines_and_beats_skyline() -> None:
    document = mixed_pieces()
    raster = optimize_layout(document, 300, spacing=3, method="RASTER")
    assert raster.method == "RASTER"
    assert sorted(p.shape_id for p in raster.placements) == sorted(s.id for s in document.shapes)
    assert overlapping_cells(document, raster.placements, 300) == 0
    assert all(p.angle % 15 == 0 for p in raster.placements)
    assert raster.used_length < raster.skyline_length < raster.baseline_length
    assert raster.waste_percent < raster.skyline_waste_percent < raster.baseline_waste_percent


def test_skyline_reports_its_own_length_as_the_comparison() -> None:
    result = optimize_layout(mixed_pieces(), 300)
    assert result.method == "SKYLINE" and result.skyline_length == result.used_length
    assert all(p.angle in (0, 90) for p in result.placements)
    assert result.layers is None


def test_per_layer_nesting_counts_area_and_sheets() -> None:
    document = PatternDocument.model_validate(flower_plate())
    result = optimize_layout(document, 300, per_layer=True, sheet=(100, 100))
    assert result.layers is not None
    assert [plan.layer_id for plan in result.layers] == ["verde", "rojo", "azul"]
    for plan in result.layers:
        shapes = [s for s in document.shapes if s.layer_id == plan.layer_id]
        assert sorted(p.shape_id for p in plan.placements) == sorted(s.id for s in shapes)
        assert plan.area_cm2 == pytest.approx(sum(area(outline(s)) for s in shapes) / 100, abs=0.01)
        for p in plan.placements:
            # Each piece lies inside its own sheet (sheets are stacked along y).
            inside = p.y - (p.y // 100) * 100
            assert inside + p.height <= 100 + 1e-6 and p.x + p.width <= 100 + 1e-6
    red = next(plan for plan in result.layers if plan.layer_id == "rojo")
    assert red.color == "#b3202a"
    # Six 24×60 mm petals with a 3 mm margin do not fit on one 100×100 mm sheet.
    assert red.sheets == 2
    assert 0 < red.waste_percent < 100


def test_raster_per_layer_on_sheets() -> None:
    document = PatternDocument.model_validate(flower_plate())
    result = optimize_layout(document, 300, method="RASTER", per_layer=True, sheet=(120, 120))
    assert result.layers is not None
    red = next(plan for plan in result.layers if plan.layer_id == "rojo")
    assert red.sheets == 1


@pytest.mark.parametrize("method", ["SKYLINE", "RASTER"])
def test_a_piece_bigger_than_the_sheet_is_reported(method: str) -> None:
    document = PatternDocument.model_validate(flower_plate())
    with pytest.raises(ValueError, match="PIECE_LARGER_THAN_SHEET"):
        optimize_layout(document, 300, method=method, per_layer=True, sheet=(30, 30))


LAYOUT = """
mutation($doc: JSON!, $sw: Float, $sh: Float, $m: LayoutMethod) {
  optimizeLayout(document: $doc, rollWidth: 300, perLayer: true, sheetWidth: $sw,
                 sheetHeight: $sh, method: $m) {
    method usedLength wastePercent skylineWastePercent baselineWastePercent elapsedMs notes
    placements { shapeId angle }
    layers { layerId color areaCm2 usedLength wastePercent sheets placements { shapeId x y angle } }
  }
}
"""


async def test_layout_per_layer_through_graphql(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    body = await gql(LAYOUT, token, doc=flower_plate(), sw=150, sh=150, m="RASTER")
    result: dict[str, Any] = body["data"]["optimizeLayout"]
    assert result["method"] == "RASTER"
    assert len(result["layers"]) == 3 and all(plan["sheets"] == 1 for plan in result["layers"])
    assert result["wastePercent"] <= result["baselineWastePercent"]

    half = await gql(LAYOUT, token, doc=flower_plate(), sw=150)
    assert half["errors"][0]["extensions"]["code"] == "INVALID_ARGUMENT"
    small = await gql(LAYOUT, token, doc=flower_plate(), sw=30, sh=30)
    assert small["errors"][0]["extensions"]["code"] == "PIECE_LARGER_THAN_SHEET"
