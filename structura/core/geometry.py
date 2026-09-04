"""Small geometric helpers, in model units (metres, radians).

Pure functions only — no model types imported here, so this module stays trivially testable.
"""

from __future__ import annotations

import math

# Distance below which two points are considered the same joint (1 mm).
NODE_MERGE_TOL = 1.0e-3

# Length below which a member is considered degenerate.
MIN_MEMBER_LENGTH = 1.0e-9


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.hypot(x2 - x1, y2 - y1)


def direction_cosines(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float]:
    """Return ``(length, c, s)`` for the vector from point 1 to point 2.

    ``c`` and ``s`` are the direction cosines of the element local x axis
    (conventions §4). Raises ``ValueError`` for a degenerate segment.
    """
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < MIN_MEMBER_LENGTH:
        raise ValueError(f"Degenerate segment: length {length!r} is below {MIN_MEMBER_LENGTH}")
    return length, dx / length, dy / length


def angle_rad(x1: float, y1: float, x2: float, y2: float) -> float:
    """Angle of the vector from point 1 to point 2, in radians, in ``(-pi, pi]``."""
    return math.atan2(y2 - y1, x2 - x1)


def angle_deg(x1: float, y1: float, x2: float, y2: float) -> float:
    """Angle of the vector from point 1 to point 2, in degrees, in ``(-180, 180]``."""
    return math.degrees(angle_rad(x1, y1, x2, y2))


def rotate_point(x: float, y: float, theta: float) -> tuple[float, float]:
    """Rotate a point about the origin by ``theta`` radians, CCW positive."""
    c, s = math.cos(theta), math.sin(theta)
    return x * c - y * s, x * s + y * c


def project_point_on_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float, float, float]:
    """Project a point onto a segment.

    Returns ``(t, qx, qy, perpendicular_distance)`` where ``t`` is the normalised position
    along the segment clamped to ``[0, 1]`` and ``(qx, qy)`` is the closest point on it.
    Used for member hit-testing and for placing a load at a point on a span.
    """
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom < MIN_MEMBER_LENGTH**2:
        return 0.0, x1, y1, distance(px, py, x1, y1)
    t = ((px - x1) * dx + (py - y1) * dy) / denom
    t = min(1.0, max(0.0, t))
    qx = x1 + t * dx
    qy = y1 + t * dy
    return t, qx, qy, distance(px, py, qx, qy)


def points_coincide(
    x1: float, y1: float, x2: float, y2: float, tol: float = NODE_MERGE_TOL
) -> bool:
    """True when two points are within the joint-merge tolerance."""
    return distance(x1, y1, x2, y2) <= tol


def is_collinear(
    x1: float, y1: float, x2: float, y2: float, x3: float, y3: float, tol: float = 1e-9
) -> bool:
    """True when three points are collinear within a cross-product tolerance."""
    cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    scale = max(1.0, distance(x1, y1, x2, y2), distance(x1, y1, x3, y3))
    return abs(cross) <= tol * scale * scale
