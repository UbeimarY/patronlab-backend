import base64
import io

import pytest
from PIL import Image

from patronlab.ai.geometry import area, outline
from patronlab.ai.nesting import optimize_layout
from patronlab.ai.palette import InvalidImageError, decode_image, extract_palette
from patronlab.ai.variations import contrast_ratio, generate_variations, score
from patronlab.document import PatternDocument, Shape
from tests.conftest import sample_document


def _png(colors: list[tuple[int, int, int]], stripe: int = 20) -> str:
    image = Image.new("RGB", (stripe * len(colors), 40))
    for i, color in enumerate(colors):
        image.paste(color, (i * stripe, 0, (i + 1) * stripe, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_palette_finds_the_colors_of_the_photo() -> None:
    image = decode_image(_png([(200, 30, 30), (20, 120, 60), (240, 220, 80)]), 1_000_000)
    palette = extract_palette(image, colors=3)
    assert sorted(c.hex for c in palette) == ["#14783c", "#c81e1e", "#f0dc50"]
    assert sum(c.share for c in palette) == pytest.approx(1, abs=0.01)


def test_palette_never_asks_for_more_clusters_than_colors() -> None:
    image = decode_image(_png([(10, 10, 10), (250, 250, 250)]), 1_000_000)
    assert len(extract_palette(image, colors=6)) == 2


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ("not base64!!", "IMAGE_NOT_BASE64"),
        (base64.b64encode(b"hello").decode(), "IMAGE_UNREADABLE"),
    ],
)
def test_invalid_images_are_rejected(payload: str, code: str) -> None:
    with pytest.raises(InvalidImageError, match=code):
        decode_image(payload, 1_000_000)


def test_images_over_the_limit_are_rejected() -> None:
    with pytest.raises(InvalidImageError, match="IMAGE_TOO_LARGE"):
        decode_image(_png([(1, 2, 3)] * 10), 100)


def test_outline_area_matches_the_rectangle() -> None:
    shape = Shape(id="a", kind="rect", x=50, y=50, width=40, height=20, rotation=30, fill="#000000")
    assert area(outline(shape)) == pytest.approx(800)


def test_contrast_ratio_matches_wcag() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1)


def test_variations_improve_the_score_and_use_the_palette() -> None:
    document = PatternDocument.model_validate(sample_document(8))
    palette = ["#1d3557", "#e9c46a", "#2a9d8f", "#e76f51"]
    original, variations = generate_variations(document, palette, count=3, seed=1)
    assert len(variations) == 3
    assert all(v.score.total >= original.total for v in variations)
    assert variations[0].score.total > original.total
    for variation in variations:
        assert {s.fill for s in variation.document.shapes} <= set(palette) | {"#b5523b"}
        assert [s.id for s in variation.document.shapes] == [s.id for s in document.shapes]


def test_the_base_piece_never_moves() -> None:
    base = {
        "id": "base",
        "kind": "rect",
        "x": 150,
        "y": 100,
        "width": 280,
        "height": 180,
        "rotation": 0,
        "fill": "#eeeeee",
    }
    raw = sample_document(6)
    raw["shapes"].insert(0, base)
    document = PatternDocument.model_validate(raw)
    _, variations = generate_variations(document, ["#1d3557", "#e9c46a"], count=3, seed=2)
    for variation in variations:
        moved = variation.document.shapes[0]
        assert (moved.x, moved.y, moved.width, moved.height, moved.rotation) == (
            150,
            100,
            280,
            180,
            0,
        )


def test_variations_are_reproducible_with_the_same_seed() -> None:
    document = PatternDocument.model_validate(sample_document(5))
    first = generate_variations(document, ["#111111", "#eeeeee"], count=2, seed=7)
    second = generate_variations(document, ["#111111", "#eeeeee"], count=2, seed=7)
    assert first == second


def test_overlapping_shapes_score_lower() -> None:
    base = sample_document(2)
    apart = PatternDocument.model_validate(base)
    base["shapes"][1].update(x=base["shapes"][0]["x"], y=base["shapes"][0]["y"])
    piled = PatternDocument.model_validate(base)
    assert score(piled, 0.1).overlap < score(apart, 0.1).overlap


def test_nesting_never_overlaps_and_beats_the_baseline() -> None:
    document = PatternDocument.model_validate(sample_document(12))
    result = optimize_layout(document, roll_width=200, spacing=3)
    placements = result.placements
    assert len(placements) == 12
    for i, a in enumerate(placements):
        assert a.x >= 0 and a.x + a.width <= 200 + 1e-6
        for b in placements[i + 1 :]:
            separated = (
                a.x + a.width <= b.x + 1e-6
                or b.x + b.width <= a.x + 1e-6
                or a.y + a.height <= b.y + 1e-6
                or b.y + b.height <= a.y + 1e-6
            )
            assert separated, (a, b)
    assert result.used_length <= result.baseline_length
    assert result.waste_percent <= result.baseline_waste_percent
    assert result.cut_travel <= result.baseline_cut_travel
    assert sorted(result.cut_order) == sorted(s["id"] for s in sample_document(12)["shapes"])


def test_a_piece_wider_than_the_roll_is_reported() -> None:
    document = PatternDocument.model_validate(sample_document(3))
    with pytest.raises(ValueError, match="PIECE_WIDER_THAN_MATERIAL"):
        optimize_layout(document, roll_width=20)
