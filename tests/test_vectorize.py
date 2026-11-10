import base64
import io
import math
from typing import Any

import pytest
from PIL import Image, ImageDraw

from patronlab.ai.colors import color_name, delta_e
from patronlab.ai.geometry import area
from patronlab.ai.vectorize import ImageTooComplexError, vectorize
from patronlab.document import PatternDocument
from tests.conftest import GraphQL

pytestmark = pytest.mark.anyio


def _circles(size: int, circles: list[tuple[int, int, int, tuple[int, int, int]]]) -> Image.Image:
    image = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for cx, cy, r, color in circles:
        draw.ellipse((cx - r, cy - r, cx + r - 1, cy + r - 1), fill=color)
    return image


def _data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _area(shape: dict[str, Any]) -> float:
    return area([(x, y) for x, y in shape["points"]])


def test_a_red_circle_on_white_is_one_layer_and_one_piece() -> None:
    # 400 px image drawn at 400 mm: a 100 px radius is a 100 mm radius.
    result = vectorize(_circles(400, [(200, 200, 100, (200, 30, 40))]), 400, 400, colors=2)
    assert len(result.layers) == 1 and len(result.shapes) == 1
    shape = result.shapes[0]
    assert _area(shape) == pytest.approx(math.pi * 100**2, rel=0.05)
    assert (shape["x"], shape["y"]) == pytest.approx((200, 200), abs=1.5)
    assert shape["layerId"] == result.layers[0].id and shape["kind"] == "path"
    assert result.layers[0].name == "Rojo carmín"
    assert any("Fondo #ffffff" in note for note in result.notes)


def test_pieces_scale_to_the_requested_size_and_form_a_valid_document() -> None:
    image = _circles(200, [(60, 60, 30, (31, 95, 160)), (140, 140, 40, (200, 30, 40))])
    result = vectorize(image, 100, 100, colors=3)
    assert {layer.name for layer in result.layers} == {"Azul cobalto", "Rojo carmín"}
    # Biggest color first (the bottom sheet).
    assert result.layers[0].area_share > result.layers[1].area_share
    areas = sorted(_area(s) for s in result.shapes)
    # The radii are 15 mm and 20 mm once the 200 px image becomes 100 mm.
    assert areas == pytest.approx([math.pi * 15**2, math.pi * 20**2], rel=0.06)
    document = PatternDocument.model_validate(
        {
            "schemaVersion": 2,
            "mode": "barniz",
            "width": 100,
            "height": 100,
            "layers": [{"id": v.id, "name": v.name, "color": v.color} for v in result.layers],
            "shapes": result.shapes,
        }
    )
    assert len(document.shapes) == 2


def test_small_specks_are_discarded_and_reported() -> None:
    image = _circles(400, [(200, 200, 100, (200, 30, 40)), (40, 40, 3, (200, 30, 40))])
    result = vectorize(image, 400, 400, colors=2, min_area=200)
    assert len(result.shapes) == 1
    assert any("Se descartaron 1 manchas" in note for note in result.notes)


def test_less_detail_means_fewer_points() -> None:
    image = _circles(400, [(200, 200, 150, (200, 30, 40))])
    fine = vectorize(image, 400, 400, colors=2, detail=1)
    coarse = vectorize(image, 400, 400, colors=2, detail=0)
    assert len(coarse.shapes[0]["points"]) < len(fine.shapes[0]["points"])


def test_a_busy_image_is_too_complex() -> None:
    image = Image.new("RGB", (400, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for row in range(0, 396, 6):
        for col in range(0, 396, 6):
            if (row + col) // 6 % 2:
                draw.rectangle((col, row, col + 5, row + 5), fill=(0, 0, 0))
    with pytest.raises(ImageTooComplexError):
        vectorize(image, 400, 400, colors=2, min_area=0)


def test_color_names_and_differences() -> None:
    assert color_name("#b3202a") == "rojo carmín"
    assert color_name("#6c8f24") == "verde oliva"
    assert delta_e("#777777", "#777777") == pytest.approx(0)
    assert delta_e("#ff0000", "#e60000") < 10 < delta_e("#ff0000", "#0000ff")


VECTORIZE = """
mutation($img: String!, $colors: Int) {
  vectorizeImage(image: $img, width: 300, height: 300, colors: $colors) {
    layers { id name color areaShare } shapes elapsedMs notes
  }
}
"""


async def test_vectorize_through_graphql(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    body = await gql(
        VECTORIZE, token, img=_data_url(_circles(300, [(150, 150, 80, (200, 30, 40))])), colors=2
    )
    result = body["data"]["vectorizeImage"]
    assert len(result["layers"]) == 1 and len(result["shapes"]) == 1
    assert result["elapsedMs"] >= 0 and result["notes"]

    assert (await gql(VECTORIZE, None, img="x"))["errors"][0]["extensions"]["code"] == (
        "UNAUTHENTICATED"
    )
    bad = await gql(VECTORIZE, token, img=_data_url(_circles(10, [])), colors=12)
    assert bad["errors"][0]["extensions"]["code"] == "INVALID_ARGUMENT"
    # 9 megapixels: over the 8 MP limit even though the PNG file is small.
    huge = await gql(VECTORIZE, token, img=_data_url(Image.new("RGB", (3000, 3000))), colors=2)
    assert huge["errors"][0]["extensions"]["code"] == "IMAGE_TOO_LARGE"
