"""A starter pattern for the demo account: a leaf cushion cover in felt."""

from typing import Any


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
            "stroke": "#2b2420",
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
            "stroke": "#2b2420",
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
                "stroke": "#2b2420",
            }
        )
    return {"width": 400, "height": 400, "background": "#f6efe3", "shapes": shapes}
