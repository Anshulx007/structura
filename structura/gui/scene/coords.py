"""The single model <-> scene coordinate mapping.

Model space is metres with **+Y up** (conventions §2). Qt scene space has +Y **down**. That
flip is applied here and nowhere else: if any other module negates a y coordinate, it is a bug.

Deliberately NOT implemented as ``view.scale(1, -1)``. A negative view scale mirrors the whole
painter, so every text label, support symbol and arrowhead would render upside down and need
individually un-mirroring. Flipping at the data boundary keeps painting ordinary.

Scene units are metres multiplied by ``SCENE_UNITS_PER_METRE``. Qt's spatial index, cosmetic
pen widths and default item sizes are all tuned for coordinates of order 1-1000, so a bare
metre scale would make a typical 6 m beam six units wide and push the interesting geometry
into the range where float noise and the BSP index behave worst.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from PySide6.QtCore import QPointF

SCENE_UNITS_PER_METRE = 100.0
"""Scene units per model metre. One centimetre of model per scene unit."""


def to_scene_x(model_x: float) -> float:
    """Model X (metres) -> scene X."""
    return model_x * SCENE_UNITS_PER_METRE


def to_scene_y(model_y: float) -> float:
    """Model Y (metres, +up) -> scene Y (+down). This is the only sign flip in the program."""
    return -model_y * SCENE_UNITS_PER_METRE


def to_scene(model_x: float, model_y: float) -> tuple[float, float]:
    """Model point -> scene point."""
    return to_scene_x(model_x), to_scene_y(model_y)


def to_model_x(scene_x: float) -> float:
    """Scene X -> model X (metres)."""
    return scene_x / SCENE_UNITS_PER_METRE


def to_model_y(scene_y: float) -> float:
    """Scene Y (+down) -> model Y (metres, +up)."""
    return -scene_y / SCENE_UNITS_PER_METRE


def to_model(scene_x: float, scene_y: float) -> tuple[float, float]:
    """Scene point -> model point."""
    return to_model_x(scene_x), to_model_y(scene_y)


def scene_length(model_length: float) -> float:
    """Convert a length (no sign flip involved) from metres to scene units."""
    return model_length * SCENE_UNITS_PER_METRE


def model_length(scene_distance: float) -> float:
    """Convert a length from scene units to metres."""
    return scene_distance / SCENE_UNITS_PER_METRE


def point_to_model(point: QPointF) -> tuple[float, float]:
    """Convenience for Qt event handlers, which hand out ``QPointF`` in scene coordinates."""
    return to_model(point.x(), point.y())
