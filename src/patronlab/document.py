"""The pattern document shared by the Angular editor and this API (schema v2).

Units are millimeters. A shape is described by its center, size and rotation,
so the same data drives the canvas, the SVG export and the AI algorithms.

Schema v2 adds the Barniz de Pasto mode: the wooden object being decorated,
ordered color layers (the resin sheets, applied bottom to top), radial repeat
groups and free-form ``path`` pieces. Documents saved before v2 have no
``schemaVersion``; :func:`upgrade` turns them into v2 whenever they are read.
"""

import copy
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

ShapeKind = Literal["rect", "ellipse", "triangle", "hexagon", "star", "leaf", "path"]
Mode = Literal["pattern", "barniz"]
# "mopa-mopa" is the resin of Barniz de Pasto; "wood" is wood cut with a laser.
MATERIALS = ("mopa-mopa", "fabric", "felt", "leather", "wood", "acrylic", "paper")
SCHEMA_VERSION = 2
MAX_SHAPES = 400  # pattern mode, as in v1
MAX_BARNIZ_SHAPES = 1500
MAX_LAYERS = 12
MIN_POINTS, MAX_POINTS = 3, 2000
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex(value: str) -> str:
    if not _HEX.match(value):
        raise ValueError("Colors must be #rrggbb")
    return value.lower()


def upgrade(raw: Any) -> Any:
    """Pure function: a v1 document (no ``schemaVersion``) becomes v2.

    v2 documents and anything that is not a dict are returned unchanged; the
    input is never modified.
    """
    if not isinstance(raw, dict) or "schemaVersion" in raw:
        return raw
    document = copy.deepcopy(raw)
    document.update(schemaVersion=SCHEMA_VERSION, mode="pattern", object=None, layers=[], groups=[])
    shapes = document.get("shapes")
    if isinstance(shapes, list):
        for shape in shapes:
            if isinstance(shape, dict):
                shape.setdefault("layerId", None)
                shape.setdefault("groupId", None)
    return document


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)


class Shape(_Model):
    id: str = Field(min_length=1, max_length=40)
    kind: ShapeKind
    x: float = Field(ge=-2000, le=2000)
    y: float = Field(ge=-2000, le=2000)
    # Paths send 0: their size is always recomputed from their points.
    width: float = Field(ge=0, le=2000)
    height: float = Field(ge=0, le=2000)
    rotation: float = Field(ge=-360, le=360)
    fill: str
    stroke: str = "#2b2420"
    layer_id: str | None = Field(default=None, max_length=40)
    group_id: str | None = Field(default=None, max_length=40)
    # Only for paths: closed polygon, millimeters relative to (x, y).
    points: list[tuple[float, float]] | None = None

    @field_validator("fill", "stroke")
    @classmethod
    def hex_color(cls, value: str) -> str:
        return _hex(value)

    @field_validator("points")
    @classmethod
    def points_in_range(
        cls, value: list[tuple[float, float]] | None
    ) -> list[tuple[float, float]] | None:
        if value is not None and any(abs(x) > 2000 or abs(y) > 2000 for x, y in value):
            raise ValueError("Points must be within 2000 mm of the center")
        return value

    @model_validator(mode="after")
    def size_and_points(self) -> "Shape":
        if self.kind == "path":
            if self.points is None or not MIN_POINTS <= len(self.points) <= MAX_POINTS:
                raise ValueError(f"A path needs between {MIN_POINTS} and {MAX_POINTS} points")
            xs = [x for x, _ in self.points]
            ys = [y for _, y in self.points]
            # Never trust the client's size for a path.
            self.width = round(max(xs) - min(xs), 3)
            self.height = round(max(ys) - min(ys), 3)
            if self.width <= 0 or self.height <= 0:
                raise ValueError("A path cannot be flat")
        else:
            if self.points is not None:
                self.points = None
            if self.width <= 0 or self.height <= 0:
                raise ValueError("Width and height must be greater than 0")
        return self


class Layer(_Model):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=40)
    color: str
    visible: bool = True
    locked: bool = False

    @field_validator("color")
    @classmethod
    def hex_color(cls, value: str) -> str:
        return _hex(value)


class Group(_Model):
    id: str = Field(min_length=1, max_length=40)
    kind: Literal["radial"] = "radial"
    count: int = Field(ge=2, le=36)
    mirror: bool = False
    source_id: str = Field(min_length=1, max_length=40)


class WoodObject(_Model):
    kind: Literal["plate", "bowl", "box", "tray"]
    width: float = Field(gt=0, le=2000)
    height: float = Field(gt=0, le=2000)
    base_color: str = "#1b1512"
    leaf: Literal["none", "gold", "silver"] = "none"

    @field_validator("base_color")
    @classmethod
    def hex_color(cls, value: str) -> str:
        return _hex(value)

    @model_validator(mode="after")
    def round_objects(self) -> "WoodObject":
        if self.kind in ("plate", "bowl") and abs(self.width - self.height) > 1e-6:
            raise ValueError("Plates and bowls are round: width must equal height")
        return self


class PatternDocument(_Model):
    schema_version: Literal[2] = SCHEMA_VERSION
    mode: Mode = "pattern"
    width: float = Field(gt=0, le=2000)
    height: float = Field(gt=0, le=2000)
    background: str = "#f6efe3"
    object: WoodObject | None = None
    layers: list[Layer] = Field(default_factory=list, max_length=MAX_LAYERS)
    groups: list[Group] = Field(default_factory=list, max_length=200)
    shapes: list[Shape] = Field(default_factory=list, max_length=MAX_BARNIZ_SHAPES)

    @model_validator(mode="before")
    @classmethod
    def from_v1(cls, raw: Any) -> Any:
        return upgrade(raw)

    @field_validator("background")
    @classmethod
    def hex_background(cls, value: str) -> str:
        return _hex(value)

    @model_validator(mode="after")
    def references(self) -> "PatternDocument":
        if self.mode == "pattern" and len(self.shapes) > MAX_SHAPES:
            raise ValueError(f"Pattern mode allows up to {MAX_SHAPES} shapes")
        if self.mode == "pattern" and self.object is not None:
            raise ValueError("Only barniz documents have a wooden object")
        layer_ids = [layer.id for layer in self.layers]
        if len(set(layer_ids)) != len(layer_ids):
            raise ValueError("Layer ids must be unique")
        group_ids = {group.id for group in self.groups}
        if len(group_ids) != len(self.groups):
            raise ValueError("Group ids must be unique")
        shape_ids = {shape.id for shape in self.shapes}
        known_layers = set(layer_ids)
        for index, shape in enumerate(self.shapes):
            if shape.layer_id is not None and shape.layer_id not in known_layers:
                raise ValueError(f"shapes.{index}: layer {shape.layer_id!r} does not exist")
            if shape.group_id is not None and shape.group_id not in group_ids:
                raise ValueError(f"shapes.{index}: group {shape.group_id!r} does not exist")
        for group in self.groups:
            if group.source_id not in shape_ids:
                raise ValueError(f"Group {group.id!r}: source {group.source_id!r} does not exist")
        return self

    def dump(self) -> dict[str, Any]:
        """JSON-ready dict with the contract's camelCase keys (``points`` only on paths)."""
        data = self.model_dump(mode="json", by_alias=True)
        for shape in data["shapes"]:
            if shape["points"] is None:
                del shape["points"]
        return data

    def layer_shapes(self) -> dict[str | None, list[Shape]]:
        """Shapes by layer id, in layer order; pieces without a layer go under None."""
        result: dict[str | None, list[Shape]] = {layer.id: [] for layer in self.layers}
        for shape in self.shapes:
            result.setdefault(shape.layer_id, []).append(shape)
        return {key: value for key, value in result.items() if value}
