"""The pattern document shared by the Angular editor and this API.

Units are millimeters. A shape is described by its center, size and rotation,
so the same data drives the canvas, the SVG export and the AI algorithms.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ShapeKind = Literal["rect", "ellipse", "triangle", "hexagon", "star", "leaf"]
MATERIALS = ("fabric", "felt", "leather", "wood", "acrylic", "paper")
MAX_SHAPES = 400
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class Shape(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=40)
    kind: ShapeKind
    x: float = Field(ge=-2000, le=2000)
    y: float = Field(ge=-2000, le=2000)
    width: float = Field(gt=0, le=2000)
    height: float = Field(gt=0, le=2000)
    rotation: float = Field(ge=-360, le=360)
    fill: str
    stroke: str = "#2b2420"

    @field_validator("fill", "stroke")
    @classmethod
    def hex_color(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError("Colors must be #rrggbb")
        return value.lower()


class PatternDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    width: float = Field(gt=0, le=2000)
    height: float = Field(gt=0, le=2000)
    background: str = "#f6efe3"
    shapes: list[Shape] = Field(default_factory=list, max_length=MAX_SHAPES)

    @field_validator("background")
    @classmethod
    def hex_background(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError("Colors must be #rrggbb")
        return value.lower()
