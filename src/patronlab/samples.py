"""Starter patterns for the demo account.

* A leaf cushion cover in felt (pattern mode).
* A Barniz de Pasto plate: an original design with a hummingbird and flowers
  on a 300 mm plate with black enamel and gold leaf, built from 4 resin
  layers applied bottom to top (green, red, blue, yellow).
"""

import math
from typing import Any

STROKE = "#2b2420"


def leaf_cushion() -> dict[str, Any]:
    shapes: list[dict[str, Any]] = [
        {
            "id": "base",
            "kind": "rect",
            "x": 200,
            "y": 200,
            "width": 300,
            "height": 300,
            "rotation": 0,
            "fill": "#e8dcc4",
            "stroke": STROKE,
        },
        {
            "id": "center",
            "kind": "hexagon",
            "x": 200,
            "y": 200,
            "width": 90,
            "height": 90,
            "rotation": 0,
            "fill": "#7a2e1f",
            "stroke": STROKE,
        },
    ]
    for i, (dx, dy, angle) in enumerate(
        [
            (0, -95, 0),
            (95, 0, 90),
            (0, 95, 180),
            (-95, 0, 270),
            (-70, -70, 315),
            (70, -70, 45),
            (70, 70, 135),
            (-70, 70, 225),
        ]
    ):
        shapes.append(
            {
                "id": f"leaf-{i + 1}",
                "kind": "leaf",
                "x": 200 + dx,
                "y": 200 + dy,
                "width": 38,
                "height": 80,
                "rotation": angle,
                "fill": "#3f6b3a" if i < 4 else "#9cae5b",
                "stroke": STROKE,
            }
        )
    return {"width": 400, "height": 400, "background": "#f6efe3", "shapes": shapes}


GREEN, RED, BLUE, YELLOW = "#3f6b3a", "#b3202a", "#1f5fa0", "#f4c430"


def _piece(
    id: str,
    kind: str,
    x: float,
    y: float,
    width: float,
    height: float,
    layer: str,
    color: str,
    rotation: float = 0,
    group: str | None = None,
    points: list[list[float]] | None = None,
) -> dict[str, Any]:
    piece: dict[str, Any] = {
        "id": id,
        "kind": kind,
        "x": round(x, 2),
        "y": round(y, 2),
        "width": width,
        "height": height,
        "rotation": rotation,
        "fill": color,
        "stroke": STROKE,
        "layerId": layer,
        "groupId": group,
    }
    if points is not None:
        piece["points"] = points
    return piece


def _radial(
    group: str,
    prefix: str,
    cx: float,
    cy: float,
    radius: float,
    count: int,
    kind: str,
    width: float,
    height: float,
    layer: str,
    color: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A radial repeat: the copies are real pieces, as the contract asks."""
    pieces = []
    for i in range(count):
        angle = 360 / count * i
        pieces.append(
            _piece(
                f"{prefix}-{i + 1}",
                kind,
                cx + radius * math.sin(math.radians(angle)),
                cy - radius * math.cos(math.radians(angle)),
                width,
                height,
                layer,
                color,
                rotation=angle,
                group=group,
            )
        )
    spec = {"id": group, "kind": "radial", "count": count, "mirror": False}
    return spec | {"sourceId": pieces[0]["id"]}, pieces


# The hummingbird drawn facing right, in millimeters around its body's center;
# it is then mirrored and turned so its beak reaches down into flower A.
BIRD_BODY = [[-30, 0], [-20, -8], [-2, -11], [16, -10], [26, -7], [32, -2], [32, 2], [24, 7]]
BIRD_BODY += [[6, 10], [-14, 9], [-26, 5]]
BIRD_WING = [[-10, -7], [-14, -26], [-6, -44], [8, -52], [4, -34], [10, -8]]
BIRD_TAIL = [[-24, -3], [-46, -14], [-56, -14], [-44, -2], [-58, 8], [-46, 10], [-24, 5]]
BIRD_BEAK = [[31, -1.6], [64, 0], [31, 1.6]]
BIRD_TURN = math.radians(-30)
BIRD_AT = (167.4, 98.0)


def _bird_point(x: float, y: float) -> tuple[float, float]:
    x = -x  # mirrored: facing left
    cos, sin = math.cos(BIRD_TURN), math.sin(BIRD_TURN)
    return BIRD_AT[0] + x * cos - y * sin, BIRD_AT[1] + x * sin + y * cos


def _bird_piece(id: str, local: list[list[float]], layer: str, color: str) -> dict[str, Any]:
    """A path piece centered on its own box, from the bird's local drawing."""
    points = [_bird_point(x, y) for x, y in local]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    relative = [[round(x - cx, 2), round(y - cy, 2)] for x, y in points]
    return _piece(id, "path", cx, cy, 0, 0, layer, color, points=relative)


def hummingbird_plate() -> dict[str, Any]:
    layers = [
        {"id": "verde", "name": "Verde hoja", "color": GREEN, "visible": True, "locked": False},
        {"id": "rojo", "name": "Rojo carmín", "color": RED, "visible": True, "locked": False},
        {"id": "azul", "name": "Azul cobalto", "color": BLUE, "visible": True, "locked": False},
        {
            "id": "amarillo",
            "name": "Amarillo azafrán",
            "color": YELLOW,
            "visible": True,
            "locked": False,
        },
    ]
    shapes: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []

    # Layer 1, green: a curved stem and its leaves.
    stem = [[-70, 40], [-40, 18], [0, 4], [40, -6], [72, -10], [72, -4], [40, 0], [0, 10]]
    stem += [[-40, 24], [-68, 44]]
    shapes.append(_piece("tallo", "path", 150, 205, 0, 0, "verde", GREEN, points=stem))
    for i, (x, y, angle) in enumerate(
        [(92, 222, 230), (122, 190, 40), (165, 214, 150), (200, 186, 30), (210, 210, 120)]
    ):
        shapes.append(_piece(f"hoja-{i + 1}", "leaf", x, y, 16, 38, "verde", GREEN, angle))

    # Layer 2, red: two flowers, each a radial repeat of petals.
    for name, cx, cy, radius, count, size in (
        ("flor-a", 92, 170, 20, 6, (14, 30)),
        ("flor-b", 222, 232, 16, 5, (12, 24)),
    ):
        group, petals = _radial(
            f"g-{name}", name, cx, cy, radius, count, "leaf", *size, "rojo", RED
        )
        groups.append(group)
        shapes.extend(petals)

    # Layer 3, blue: the hummingbird (body, wing and forked tail), drinking from flower A.
    shapes.append(_bird_piece("colibri-cola", BIRD_TAIL, "azul", BLUE))
    shapes.append(_bird_piece("colibri-cuerpo", BIRD_BODY, "azul", BLUE))
    shapes.append(_bird_piece("colibri-ala", BIRD_WING, "azul", BLUE))

    # Layer 4, yellow: flower centers, the beak, the eye and a rim of dots.
    shapes.append(_piece("centro-a", "ellipse", 92, 170, 14, 14, "amarillo", YELLOW))
    shapes.append(_piece("centro-b", "ellipse", 222, 232, 11, 11, "amarillo", YELLOW))
    shapes.append(_bird_piece("colibri-pico", BIRD_BEAK, "amarillo", YELLOW))
    eye_x, eye_y = _bird_point(22, -3)
    shapes.append(_piece("colibri-ojo", "ellipse", eye_x, eye_y, 5, 5, "amarillo", YELLOW))
    rim, dots = _radial(
        "g-cenefa", "cenefa", 150, 150, 134, 16, "ellipse", 8, 8, "amarillo", YELLOW
    )
    groups.append(rim)
    shapes.extend(dots)

    return {
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
        "layers": layers,
        "groups": groups,
        "shapes": shapes,
    }
