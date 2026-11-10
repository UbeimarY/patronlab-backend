import copy
import math
from typing import Any

import pytest
from pydantic import ValidationError

from patronlab.ai.geometry import area, outline
from patronlab.document import PatternDocument, Shape, upgrade
from patronlab.samples import leaf_cushion
from tests.conftest import sample_document


def barniz_document(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schemaVersion": 2,
        "mode": "barniz",
        "width": 300,
        "height": 300,
        "background": "#f6efe3",
        "object": {
            "kind": "plate",
            "width": 300,
            "height": 300,
            "baseColor": "#1b1512",
            "leaf": "gold",
        },
        "layers": [
            {"id": "l-1", "name": "Rojo", "color": "#b3202a", "visible": True, "locked": False}
        ],
        "groups": [{"id": "g-1", "kind": "radial", "count": 6, "mirror": False, "sourceId": "s-1"}],
        "shapes": [
            {
                "id": "s-1",
                "kind": "leaf",
                "x": 150,
                "y": 80,
                "width": 30,
                "height": 60,
                "rotation": 0,
                "fill": "#b3202a",
                "stroke": "#2b2420",
                "layerId": "l-1",
                "groupId": "g-1",
            },
            {
                "id": "s-2",
                "kind": "path",
                "x": 150,
                "y": 150,
                "width": 0,
                "height": 0,
                "rotation": 0,
                "fill": "#1f5fa0",
                "stroke": "#2b2420",
                "layerId": "l-1",
                "groupId": None,
                "points": [[-20, -10], [25, -5], [5, 20]],
            },
        ],
    }
    document.update(changes)
    return document


def test_upgrade_turns_v1_into_v2_without_touching_the_input() -> None:
    v1 = leaf_cushion()
    before = copy.deepcopy(v1)
    v2 = upgrade(v1)
    assert v1 == before
    assert v2["schemaVersion"] == 2
    assert (v2["mode"], v2["object"], v2["layers"], v2["groups"]) == ("pattern", None, [], [])
    assert all(s["layerId"] is None and s["groupId"] is None for s in v2["shapes"])
    assert upgrade(v2) is v2  # already v2: unchanged


def test_v1_documents_validate_and_dump_as_v2() -> None:
    dumped = PatternDocument.model_validate(sample_document(3)).dump()
    assert dumped["schemaVersion"] == 2 and dumped["mode"] == "pattern"
    assert set(dumped["shapes"][0]) == {
        "id",
        "kind",
        "x",
        "y",
        "width",
        "height",
        "rotation",
        "fill",
        "stroke",
        "layerId",
        "groupId",
    }
    # Dumping and reading again is stable.
    assert PatternDocument.model_validate(dumped).dump() == dumped


def test_a_barniz_document_round_trips_with_camel_case_keys() -> None:
    dumped = PatternDocument.model_validate(barniz_document()).dump()
    assert dumped["object"]["baseColor"] == "#1b1512"
    assert dumped["groups"][0]["sourceId"] == "s-1"
    path = dumped["shapes"][1]
    assert path["points"] == [[-20, -10], [25, -5], [5, 20]]
    # The server recomputes the size of a path from its points.
    assert (path["width"], path["height"]) == (45, 30)


def test_path_outline_is_rotated_and_translated() -> None:
    shape = Shape(
        id="p",
        kind="path",
        x=100,
        y=50,
        width=0,
        height=0,
        rotation=90,
        fill="#000000",
        points=[(0, 0), (10, 0), (10, 20), (0, 20)],
    )
    points = outline(shape)
    assert points[1] == pytest.approx((100, 60))
    assert area(points) == pytest.approx(200)


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([[0, 0], [1, 1]], "between 3 and 2000"),
        ([[0, 0], [5, 0], [10, 0]], "flat"),
        (None, "between 3 and 2000"),
        ([[0, 0], [5000, 0], [0, 5]], "within 2000"),
    ],
)
def test_invalid_paths_are_rejected(points: Any, message: str) -> None:
    raw = barniz_document()
    raw["shapes"][1]["points"] = points
    with pytest.raises(ValidationError, match=message):
        PatternDocument.model_validate(raw)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["shapes"][0].update(layerId="l-9"), "layer 'l-9' does not exist"),
        (lambda d: d["shapes"][0].update(groupId="g-9"), "group 'g-9' does not exist"),
        (lambda d: d["groups"][0].update(sourceId="nope"), "source 'nope' does not exist"),
        (lambda d: d["object"].update(height=200), "round"),
        (lambda d: d.update(mode="pattern"), "Only barniz"),
        (lambda d: d["layers"].append(dict(d["layers"][0])), "unique"),
    ],
)
def test_references_and_objects_are_checked(change: Any, message: str) -> None:
    raw = barniz_document()
    change(raw)
    with pytest.raises(ValidationError, match=message):
        PatternDocument.model_validate(raw)


def _many(count: int, mode: str) -> dict[str, Any]:
    raw = barniz_document(mode=mode, groups=[])
    if mode == "pattern":
        raw["object"] = None
    shape = raw["shapes"][0] | {"groupId": None}
    raw["shapes"] = [shape | {"id": f"s{i}"} for i in range(count)]
    return raw


def test_limits_on_pieces_and_layers() -> None:
    PatternDocument.model_validate(_many(400, "pattern"))
    with pytest.raises(ValidationError, match="up to 400"):
        PatternDocument.model_validate(_many(401, "pattern"))
    PatternDocument.model_validate(_many(1500, "barniz"))
    with pytest.raises(ValidationError):
        PatternDocument.model_validate(_many(1501, "barniz"))
    raw = barniz_document()
    raw["layers"] = [raw["layers"][0] | {"id": f"l-{i}"} for i in range(13)]
    with pytest.raises(ValidationError):
        PatternDocument.model_validate(raw)


def test_shoelace_area_of_a_regular_polygon() -> None:
    shape = Shape(
        id="e", kind="ellipse", x=0, y=0, width=100, height=100, rotation=0, fill="#000000"
    )
    # 48-gon inscribed in a circle of radius 50.
    assert area(outline(shape)) == pytest.approx(24 * 50**2 * math.sin(2 * math.pi / 48))
