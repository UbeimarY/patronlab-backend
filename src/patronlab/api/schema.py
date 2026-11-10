"""GraphQL schema: artisans, patterns with versions, and the AI tools.

Why GraphQL here: the editor asks for exactly what each screen needs (the list
shows names and dates; the editor loads one full document; the history shows
version numbers only) in a single request, with a typed, self-documenting API.
"""

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import strawberry
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from strawberry.extensions import MaxTokensLimiter, QueryDepthLimiter
from strawberry.scalars import JSON
from strawberry.types import Info

from patronlab.ai.nesting import optimize_layout
from patronlab.ai.palette import InvalidImageError, decode_image, extract_palette
from patronlab.ai.variations import generate_variations
from patronlab.api.context import Context
from patronlab.api.errors import AppError, mask_errors, not_found
from patronlab.db.models import Pattern, PatternVersion, User
from patronlab.document import MATERIALS, MAX_POINTS, PatternDocument, upgrade
from patronlab.security import hash_password, issue_token, verify_password

MAX_PATTERNS_PER_USER = 200
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


# ---------- Types ----------


@strawberry.type
class UserType:
    id: strawberry.ID
    email: str
    full_name: str
    craft: str | None

    @staticmethod
    def of(user: User) -> "UserType":
        return UserType(
            id=strawberry.ID(str(user.id)),
            email=user.email,
            full_name=user.full_name,
            craft=user.craft,
        )


@strawberry.type
class AuthPayload:
    token: str
    expires_at: datetime
    user: UserType


@strawberry.type
class VersionType:
    number: int
    note: str
    shape_count: int
    created_at: datetime


@strawberry.type
class PatternType:
    id: strawberry.ID
    name: str
    material: str
    current_version: int
    created_at: datetime
    updated_at: datetime
    mode: str = strawberry.field(description='"pattern" or "barniz", from the current version.')
    piece_count: int
    layer_count: int
    _pattern: strawberry.Private[Pattern]

    @staticmethod
    def of(pattern: Pattern, summary: "Summary") -> "PatternType":
        mode, piece_count, layer_count = summary
        return PatternType(
            id=strawberry.ID(str(pattern.id)),
            name=pattern.name,
            material=pattern.material,
            current_version=pattern.current_version,
            created_at=pattern.created_at,
            updated_at=pattern.updated_at,
            mode=mode,
            piece_count=piece_count,
            layer_count=layer_count,
            _pattern=pattern,
        )

    @strawberry.field(description="The document of the current version, or of a given one.")
    async def document(self, info: Info[Context, None], version: int | None = None) -> JSON:
        number = version or self._pattern.current_version
        row = await info.context.session.scalar(
            select(PatternVersion.document).where(
                PatternVersion.pattern_id == self._pattern.id, PatternVersion.number == number
            )
        )
        if row is None:
            raise AppError("VERSION_NOT_FOUND", f"La versión {number} no existe.")
        return upgrade(row)

    @strawberry.field(description="Saved versions, newest first.")
    async def versions(self, info: Info[Context, None]) -> list[VersionType]:
        rows = await info.context.session.scalars(
            select(PatternVersion)
            .where(PatternVersion.pattern_id == self._pattern.id)
            .order_by(PatternVersion.number.desc())
        )
        return [
            VersionType(
                number=v.number, note=v.note, shape_count=v.shape_count, created_at=v.created_at
            )
            for v in rows
        ]


@strawberry.type
class PaletteColorType:
    hex: str
    share: float = strawberry.field(description="Fraction of the photo covered by this color.")


@strawberry.type
class ScoreType:
    total: float
    balance: float
    overlap: float
    contrast: float
    coverage: float


@strawberry.type
class VariationType:
    document: JSON
    score: ScoreType


@strawberry.type
class VariationsResult:
    original: ScoreType
    variations: list[VariationType]


@strawberry.type
class PlacementType:
    shape_id: str
    x: float
    y: float
    width: float
    height: float
    rotated: bool


@strawberry.type
class LayoutType:
    placements: list[PlacementType]
    used_length: float
    waste_percent: float
    baseline_length: float
    baseline_waste_percent: float
    cut_order: list[str]
    cut_travel: float
    baseline_cut_travel: float


# ---------- Inputs ----------


@strawberry.input
class RegisterInput:
    email: str
    password: str
    full_name: str
    craft: str | None = None


@strawberry.input
class CreatePatternInput:
    name: str
    material: str
    document: JSON


@strawberry.input
class SavePatternInput:
    id: strawberry.ID
    base_version: int = strawberry.field(description="The version this edit started from.")
    document: JSON
    note: str = ""
    material: str | None = None


# ---------- Helpers ----------

# (mode, piece count, layer count) of a version: stored in columns, never read from the JSONB.
Summary = tuple[str, int, int]


def _summary_of(document: PatternDocument) -> Summary:
    return document.mode, len(document.shapes), len(document.layers)


def _with_summary() -> Any:
    """Patterns joined with the summary columns of their current version."""
    return select(
        Pattern, PatternVersion.mode, PatternVersion.shape_count, PatternVersion.layer_count
    ).join(
        PatternVersion,
        (PatternVersion.pattern_id == Pattern.id)
        & (PatternVersion.number == Pattern.current_version),
    )


async def _pattern_type(info: Info[Context, None], pattern: Pattern) -> PatternType:
    row = (
        await info.context.session.execute(
            select(
                PatternVersion.mode, PatternVersion.shape_count, PatternVersion.layer_count
            ).where(
                PatternVersion.pattern_id == pattern.id,
                PatternVersion.number == pattern.current_version,
            )
        )
    ).one()
    return PatternType.of(pattern, (row[0], row[1], row[2]))


def _version_row(
    pattern: Pattern, number: int, document: PatternDocument, note: str
) -> PatternVersion:
    mode, pieces, layers = _summary_of(document)
    return PatternVersion(
        pattern_id=pattern.id,
        number=number,
        document=document.dump(),
        note=note,
        shape_count=pieces,
        mode=mode,
        layer_count=layers,
    )


def _document(raw: Any) -> PatternDocument:
    """Validates a document (v1 is upgraded to v2) or explains every problem found."""
    shapes = raw.get("shapes") if isinstance(raw, dict) else None
    if isinstance(shapes, list):
        for index, shape in enumerate(shapes):
            points = shape.get("points") if isinstance(shape, dict) else None
            if isinstance(points, list) and len(points) > MAX_POINTS:
                raise AppError(
                    "TOO_MANY_POINTS",
                    f"La pieza {index + 1} tiene {len(points)} puntos; el máximo es {MAX_POINTS}.",
                )
    try:
        return PatternDocument.model_validate(raw)
    except ValidationError as error:
        problems = [
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}".lstrip(": ") for e in error.errors()[:5]
        ]
        raise AppError("INVALID_DOCUMENT", "El diseño no es válido.", problems=problems) from error


def _palette(colors: list[str]) -> list[str]:
    cleaned = [c.lower() for c in colors[:8] if _HEX.match(c)]
    if len(cleaned) != len(colors[:8]) or not cleaned:
        raise AppError("INVALID_PALETTE", "La paleta debe tener de 1 a 8 colores #rrggbb.")
    return cleaned


def _name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise AppError("INVALID_NAME", "El nombre debe tener entre 1 y 100 caracteres.")
    return value


def _material(value: str) -> str:
    if value not in MATERIALS:
        raise AppError("INVALID_MATERIAL", "Material no soportado.", allowed=list(MATERIALS))
    return value


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise not_found() from error


async def _owned_pattern(
    info: Info[Context, None], pattern_id: str, *, lock: bool = False
) -> Pattern:
    user = await info.context.user()
    query = select(Pattern).where(Pattern.id == _uuid(pattern_id), Pattern.owner_id == user.id)
    if lock:
        query = query.with_for_update()
    pattern = await info.context.session.scalar(query)
    if pattern is None:
        raise not_found()
    return pattern


async def _add_version(
    info: Info[Context, None],
    pattern: Pattern,
    base_version: int,
    document: PatternDocument,
    note: str,
) -> PatternType:
    """Optimistic concurrency: only an edit based on the latest version is saved.

    The row lock serializes two saves of the same pattern; the unique
    (pattern, number) constraint is the last line of defense.
    """
    if base_version != pattern.current_version:
        raise AppError(
            "VERSION_CONFLICT",
            "Este patrón cambió en otra pestaña o dispositivo. Recarga para ver la última versión.",
            currentVersion=pattern.current_version,
        )
    session = info.context.session
    pattern.current_version += 1
    pattern.updated_at = func.now()
    session.add(_version_row(pattern, pattern.current_version, document, note.strip()[:200]))
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise AppError("VERSION_CONFLICT", "Otra edición se guardó primero.") from error
    await session.refresh(pattern)
    return PatternType.of(pattern, _summary_of(document))


async def _session_for(info: Info[Context, None], user: User) -> AuthPayload:
    settings = info.context.settings
    token, expires_at = issue_token(
        settings.jwt_secret, user.id, "artisan", timedelta(days=settings.jwt_expire_days)
    )
    return AuthPayload(token=token, expires_at=expires_at, user=UserType.of(user))


# ---------- Operations ----------


@strawberry.type
class Query:
    @strawberry.field
    async def me(self, info: Info[Context, None]) -> UserType:
        return UserType.of(await info.context.user())

    @strawberry.field(description="My patterns, last edited first.")
    async def patterns(self, info: Info[Context, None]) -> list[PatternType]:
        user = await info.context.user()
        rows = await info.context.session.execute(
            _with_summary().where(Pattern.owner_id == user.id).order_by(Pattern.updated_at.desc())
        )
        return [PatternType.of(p, (mode, pieces, layers)) for p, mode, pieces, layers in rows]

    @strawberry.field
    async def pattern(self, info: Info[Context, None], id: strawberry.ID) -> PatternType:
        return await _pattern_type(info, await _owned_pattern(info, id))

    @strawberry.field(description="Materials the editor and the optimizer support.")
    def materials(self) -> list[str]:
        return list(MATERIALS)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def register(self, info: Info[Context, None], input: RegisterInput) -> AuthPayload:
        from email_validator import EmailNotValidError, validate_email

        try:
            email = validate_email(
                input.email.strip(), check_deliverability=False
            ).normalized.lower()
        except EmailNotValidError as error:
            raise AppError("INVALID_EMAIL", "Escribe un correo válido.") from error
        if not 8 <= len(input.password) <= 128:
            raise AppError("WEAK_PASSWORD", "La contraseña debe tener entre 8 y 128 caracteres.")
        full_name = input.full_name.strip()
        if not 2 <= len(full_name) <= 100:
            raise AppError("INVALID_NAME", "Escribe tu nombre (2 a 100 caracteres).")
        craft = (input.craft or "").strip()[:50] or None

        session = info.context.session
        user = User(
            email=email,
            full_name=full_name,
            craft=craft,
            password_hash=await hash_password(input.password),
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise AppError("EMAIL_TAKEN", "Ya existe una cuenta con ese correo.") from error
        return await _session_for(info, user)

    @strawberry.mutation
    async def login(self, info: Info[Context, None], email: str, password: str) -> AuthPayload:
        user = await info.context.session.scalar(
            select(User).where(User.email == email.strip().lower())
        )
        # Same message for unknown email and wrong password: no account enumeration.
        if (
            not await verify_password(password, user.password_hash if user else None)
            or user is None
        ):
            raise AppError("INVALID_CREDENTIALS", "Correo o contraseña incorrectos.")
        return await _session_for(info, user)

    @strawberry.mutation
    async def create_pattern(
        self, info: Info[Context, None], input: CreatePatternInput
    ) -> PatternType:
        user = await info.context.user()
        session = info.context.session
        owned = await session.scalar(
            select(func.count()).select_from(Pattern).where(Pattern.owner_id == user.id)
        )
        if owned >= MAX_PATTERNS_PER_USER:
            raise AppError("LIMIT_REACHED", f"Puedes tener hasta {MAX_PATTERNS_PER_USER} patrones.")
        document = _document(input.document)
        pattern = Pattern(
            owner_id=user.id,
            name=_name(input.name),
            material=_material(input.material),
            current_version=1,
        )
        session.add(pattern)
        await session.flush()
        session.add(_version_row(pattern, 1, document, "Versión inicial"))
        await session.commit()
        await session.refresh(pattern)
        return PatternType.of(pattern, _summary_of(document))

    @strawberry.mutation(
        description="Saves a new version. Fails with VERSION_CONFLICT if baseVersion is stale."
    )
    async def save_pattern(self, info: Info[Context, None], input: SavePatternInput) -> PatternType:
        document = _document(input.document)
        material = _material(input.material) if input.material else None
        pattern = await _owned_pattern(info, input.id, lock=True)
        if material and input.base_version == pattern.current_version:
            pattern.material = material
        return await _add_version(info, pattern, input.base_version, document, input.note)

    @strawberry.mutation(description="Restores an old version by saving it as the newest one.")
    async def restore_version(
        self, info: Info[Context, None], id: strawberry.ID, number: int, base_version: int
    ) -> PatternType:
        pattern = await _owned_pattern(info, id, lock=True)
        raw = await info.context.session.scalar(
            select(PatternVersion.document).where(
                PatternVersion.pattern_id == pattern.id, PatternVersion.number == number
            )
        )
        if raw is None:
            raise AppError("VERSION_NOT_FOUND", f"La versión {number} no existe.")
        return await _add_version(
            info, pattern, base_version, _document(raw), f"Restaurada desde la versión {number}"
        )

    @strawberry.mutation
    async def rename_pattern(
        self, info: Info[Context, None], id: strawberry.ID, name: str
    ) -> PatternType:
        pattern = await _owned_pattern(info, id, lock=True)
        pattern.name = _name(name)
        await info.context.session.commit()
        await info.context.session.refresh(pattern)
        return await _pattern_type(info, pattern)

    @strawberry.mutation
    async def delete_pattern(self, info: Info[Context, None], id: strawberry.ID) -> bool:
        pattern = await _owned_pattern(info, id, lock=True)
        await info.context.session.delete(pattern)
        await info.context.session.commit()
        return True

    # ----- AI tools: CPU work runs in a thread so the server keeps answering. -----

    @strawberry.mutation(description="K-means palette from a photo (data URL or base64).")
    async def extract_palette(
        self, info: Info[Context, None], image: str, colors: int = 5
    ) -> list[PaletteColorType]:
        await info.context.user()
        if not 2 <= colors <= 8:
            raise AppError("INVALID_ARGUMENT", "Pide entre 2 y 8 colores.")
        try:
            picture = decode_image(image, info.context.settings.max_image_bytes)
        except InvalidImageError as error:
            message = {
                "IMAGE_TOO_LARGE": "La imagen es muy pesada (máximo 4 MB).",
                "IMAGE_NOT_BASE64": "No se pudo leer la imagen.",
            }.get(str(error), "El archivo no es una imagen válida.")
            raise AppError(str(error), message) from error
        palette = await asyncio.to_thread(extract_palette, picture, colors)
        return [PaletteColorType(hex=c.hex, share=c.share) for c in palette]

    @strawberry.mutation(description="Evolutionary search of design variations using the palette.")
    async def generate_variations(
        self,
        info: Info[Context, None],
        document: JSON,
        palette: list[str],
        count: int = 4,
        seed: int = 0,
    ) -> VariationsResult:
        await info.context.user()
        parsed = _document(document)
        if not 1 <= count <= 6:
            raise AppError("INVALID_ARGUMENT", "Pide entre 1 y 6 variaciones.")
        if len(parsed.shapes) > 120:
            raise AppError("TOO_MANY_SHAPES", "Las variaciones admiten hasta 120 piezas.")
        colors = _palette(palette)
        try:
            original, variations = await asyncio.to_thread(
                generate_variations, parsed, colors, count, seed
            )
        except ValueError as error:
            raise AppError(
                str(error), "Agrega piezas y una paleta antes de generar variaciones."
            ) from error
        return VariationsResult(
            original=ScoreType(**_score(original)),
            variations=[
                VariationType(document=v.document.dump(), score=ScoreType(**_score(v.score)))
                for v in variations
            ],
        )

    @strawberry.mutation(description="Nesting on a roll of material and cutting order.")
    async def optimize_layout(
        self, info: Info[Context, None], document: JSON, roll_width: float, spacing: float = 3.0
    ) -> LayoutType:
        await info.context.user()
        parsed = _document(document)
        if not 10 <= roll_width <= 5000 or not 0 <= spacing <= 50:
            raise AppError("INVALID_ARGUMENT", "Ancho entre 10 y 5000 mm; margen entre 0 y 50 mm.")
        try:
            result = await asyncio.to_thread(optimize_layout, parsed, roll_width, spacing)
        except ValueError as error:
            message = (
                "Hay una pieza más ancha que el material."
                if str(error) == "PIECE_WIDER_THAN_MATERIAL"
                else "Agrega piezas antes de optimizar."
            )
            raise AppError(str(error), message) from error
        return LayoutType(
            placements=[PlacementType(**vars_of(p)) for p in result.placements],
            used_length=result.used_length,
            waste_percent=result.waste_percent,
            baseline_length=result.baseline_length,
            baseline_waste_percent=result.baseline_waste_percent,
            cut_order=result.cut_order,
            cut_travel=result.cut_travel,
            baseline_cut_travel=result.baseline_cut_travel,
        )


def _score(score: Any) -> dict[str, float]:
    return {
        name: getattr(score, name)
        for name in ("total", "balance", "overlap", "contrast", "coverage")
    }


def vars_of(placement: Any) -> dict[str, Any]:
    return {
        name: getattr(placement, name)
        for name in ("shape_id", "x", "y", "width", "height", "rotated")
    }


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        # Cheap protection against abusive queries.
        lambda: QueryDepthLimiter(max_depth=10),
        lambda: MaxTokensLimiter(max_token_count=2000),
        mask_errors,
    ],
)
