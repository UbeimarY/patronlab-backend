"""Errors the client is meant to see, each with a stable machine-readable code.

Anything else raised inside a resolver is masked as "Unexpected error", so
stack traces, SQL or internal details never reach the browser.
"""

from typing import Any

from graphql import GraphQLError
from strawberry.extensions import MaskErrors


class AppError(GraphQLError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message, extensions={"code": code, **details})


def _should_mask(error: GraphQLError) -> bool:
    original = error.original_error
    # Errors without an original are GraphQL's own (syntax, validation): safe to show.
    return original is not None and not isinstance(original, AppError)


def mask_errors() -> MaskErrors:
    return MaskErrors(should_mask_error=_should_mask, error_message="Unexpected error")


def unauthenticated() -> AppError:
    return AppError("UNAUTHENTICATED", "Inicia sesión para continuar.")


def not_found() -> AppError:
    return AppError("NOT_FOUND", "El patrón no existe o no es tuyo.")
