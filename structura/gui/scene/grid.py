"""Adaptive grid spacing.

Pure arithmetic, deliberately free of Qt so it can be unit-tested headlessly. The painting
itself lives in ``canvas_scene.drawBackground``.

A fixed grid is useless in a CAD view: at 100x zoom a 1 m grid is an unreadable smear, and at
0.01x it is a single line. So the spacing is chosen from a 1-2-5 decade sequence - the same
progression engineering rulers and chart axes use - picking the smallest step that still keeps
grid lines at least ``MIN_PIXELS`` apart on screen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .coords import SCENE_UNITS_PER_METRE

MIN_MINOR_PIXELS = 12.0
"""Minor grid lines closer together than this on screen are too dense to read."""

MAJOR_EVERY = 5
"""Every fifth minor line is drawn as a major line, matching the 1-2-5 sequence."""

_MANTISSAS = (1.0, 2.0, 5.0)


@dataclass(frozen=True, slots=True)
class GridSpacing:
    """The chosen grid step, in model and scene units."""

    minor_metres: float
    major_metres: float

    @property
    def minor_scene(self) -> float:
        return self.minor_metres * SCENE_UNITS_PER_METRE

    @property
    def major_scene(self) -> float:
        return self.major_metres * SCENE_UNITS_PER_METRE

    def label(self) -> str:
        """Human-readable step for a status bar, e.g. ``"200 mm"`` or ``"5 m"``."""
        if self.minor_metres >= 1.0:
            return f"{self.minor_metres:g} m"
        return f"{self.minor_metres * 1000.0:g} mm"


def choose_spacing(view_scale: float, min_pixels: float = MIN_MINOR_PIXELS) -> GridSpacing:
    """Pick a 1-2-5 grid step that keeps minor lines at least ``min_pixels`` apart.

    ``view_scale`` is the view transform's scale factor: device pixels per scene unit. A
    non-positive or non-finite scale (a collapsed or not-yet-shown view) falls back to a 1 m
    grid rather than dividing by zero.
    """
    if not math.isfinite(view_scale) or view_scale <= 0.0:
        return GridSpacing(1.0, float(MAJOR_EVERY))

    # Smallest model-space step whose on-screen size is still readable.
    min_metres = min_pixels / (view_scale * SCENE_UNITS_PER_METRE)
    if min_metres <= 0.0 or not math.isfinite(min_metres):
        return GridSpacing(1.0, float(MAJOR_EVERY))

    decade = math.floor(math.log10(min_metres))
    for exponent in (decade, decade + 1):
        for mantissa in _MANTISSAS:
            step = mantissa * (10.0**exponent)
            if step >= min_metres:
                return GridSpacing(step, step * MAJOR_EVERY)

    # Unreachable for finite inputs; kept so the function is total.
    step = 10.0 ** (decade + 1)
    return GridSpacing(step, step * MAJOR_EVERY)


def snap_value(value: float, step: float) -> float:
    """Round one coordinate to the nearest multiple of ``step``."""
    if step <= 0.0:
        return value
    return round(value / step) * step


def grid_lines(low: float, high: float, step: float) -> list[float]:
    """Every multiple of ``step`` within ``[low, high]``, for painting one axis.

    Returns an empty list when the range would need an unreasonable number of lines, which
    protects ``drawBackground`` from a pathological transform rather than freezing the UI.
    """
    if step <= 0.0 or high < low:
        return []
    count = (high - low) / step
    if not math.isfinite(count) or count > 10_000:
        return []
    first = math.ceil(low / step)
    last = math.floor(high / step)
    return [index * step for index in range(int(first), int(last) + 1)]
