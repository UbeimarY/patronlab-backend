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
