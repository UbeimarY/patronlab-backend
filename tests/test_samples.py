from graphql import GraphQLError

from patronlab.api.errors import AppError, _should_mask
from patronlab.document import PatternDocument
from patronlab.samples import leaf_cushion


def test_the_starter_pattern_is_a_valid_document() -> None:
    document = PatternDocument.model_validate(leaf_cushion())
    assert len(document.shapes) == 10


def test_internal_errors_are_masked_but_app_errors_are_not() -> None:
    assert _should_mask(GraphQLError("boom", original_error=RuntimeError("select * from users")))
    assert not _should_mask(GraphQLError("x", original_error=AppError("CODE", "message")))
    assert not _should_mask(GraphQLError("Syntax Error"))


def test_the_barniz_plate_is_a_valid_barniz_document() -> None:
    import math

    from patronlab.ai.geometry import outline
    from patronlab.samples import hummingbird_plate

    document = PatternDocument.model_validate(hummingbird_plate())
    assert document.mode == "barniz" and len(document.layers) == 4
    assert document.object is not None
    assert (document.object.kind, document.object.width, document.object.leaf) == (
        "plate",
        300,
        "gold",
    )
    assert document.object.base_color == "#1b1512"
    # Every sheet is cut from its layer's resin, and everything fits on the plate.
    colors = {layer.id: layer.color for layer in document.layers}
    for shape in document.shapes:
        assert shape.fill == colors[shape.layer_id]
        for x, y in outline(shape):
            assert math.hypot(x - 150, y - 150) < 150
    assert {g.id for g in document.groups} == {"g-flor-a", "g-flor-b", "g-cenefa"}
    assert any(s.kind == "path" for s in document.shapes)
