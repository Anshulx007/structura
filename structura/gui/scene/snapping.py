"""Snapping.

Qt-free by design: everything here is arithmetic over the model, so the behaviour that decides
where a click actually lands can be unit-tested without a window.

Priority order, highest first:

1. **Existing node** - connecting to a joint is almost always the intent, and getting it wrong
   silently creates a duplicate joint that looks connected but transfers no force.
2. **Point on a member** - for placing a joint on an existing span.
3. **Angle constraint** - when Shift is held and an anchor exists.
4. **Grid**.

Tolerances arrive in *model* units. The caller converts from a pixel tolerance using the
current view scale, so the grab radius stays a constant size on screen at any zoom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ...core import geometry
from ...core.model import Structure

ANGLE_SNAP_DEGREES = 15.0
"""Shift constrains directions to multiples of this, so 30/45/60/90 are all reachable."""

DEFAULT_PIXEL_TOLERANCE = 10.0
"""Grab radius in device pixels. Independent of zoom."""


class SnapKind(str, Enum):
    """What a snapped point latched onto. Drives the on-canvas indicator and status text."""

    FREE = "free"
    GRID = "grid"
    NODE = "node"
    MEMBER = "member"
    ANGLE = "angle"


@dataclass(frozen=True, slots=True)
class SnapResult:
    """Where a click or cursor position actually lands, and why."""

    x: float
    y: float
    kind: SnapKind
    node_id: int | None = None
    member_id: int | None = None

    @property
    def is_existing_node(self) -> bool:
        return self.kind is SnapKind.NODE and self.node_id is not None

    @property
    def is_on_member(self) -> bool:
        return self.kind is SnapKind.MEMBER and self.member_id is not None

    def describe(self) -> str:
        """Short status-bar text. ASCII only - the status bar mirrors into the console."""
        match self.kind:
            case SnapKind.NODE:
                return f"Node {self.node_id}"
            case SnapKind.MEMBER:
                return f"On member {self.member_id}"
            case SnapKind.GRID:
                return "Grid"
            case SnapKind.ANGLE:
                return "Angle"
            case _:
                return "Free"


@dataclass(slots=True)
class SnapSettings:
    """User-toggleable snap behaviour, owned by the main window."""

    to_nodes: bool = True
    to_members: bool = True
    to_grid: bool = True
    pixel_tolerance: float = DEFAULT_PIXEL_TOLERANCE
    angle_step_degrees: float = ANGLE_SNAP_DEGREES


def snap_point(
    structure: Structure,
    x: float,
    y: float,
    *,
    tolerance: float,
    grid_step: float,
    settings: SnapSettings | None = None,
    anchor: tuple[float, float] | None = None,
    constrain_angle: bool = False,
) -> SnapResult:
    """Resolve a raw model-space point to where it should actually go.

    ``tolerance`` is the grab radius in **model units** (metres). ``anchor`` is the point a
    rubber-band operation started from, needed for the angle constraint.
    """
    settings = settings or SnapSettings()

    if settings.to_nodes:
        node = _nearest_node(structure, x, y, tolerance)
        if node is not None:
            return SnapResult(node.x, node.y, SnapKind.NODE, node_id=node.id)

    if settings.to_members:
        hit = _nearest_member_point(structure, x, y, tolerance)
        if hit is not None:
            member_id, px, py = hit
            return SnapResult(px, py, SnapKind.MEMBER, member_id=member_id)

    if constrain_angle and anchor is not None:
        ax, ay = anchor
        cx, cy = _constrain_to_angle(ax, ay, x, y, settings.angle_step_degrees, grid_step)
        return _as_node_if_coincident(structure, cx, cy, SnapKind.ANGLE, settings)

    if settings.to_grid and grid_step > 0.0:
        return _as_node_if_coincident(
            structure,
            round(x / grid_step) * grid_step,
            round(y / grid_step) * grid_step,
            SnapKind.GRID,
            settings,
        )

    return _as_node_if_coincident(structure, x, y, SnapKind.FREE, settings)


def _as_node_if_coincident(
    structure: Structure, x: float, y: float, kind: SnapKind, settings: SnapSettings
) -> SnapResult:
    """Report an existing joint when the *snapped* point has landed on one.

    The node test earlier in ``snap_point`` measures from the raw cursor, which can be further
    than the grab radius from a joint that the grid then rounds straight onto. Without this
    second check the caller sees a plain grid hit and happily creates a second joint at
    coordinates a joint already occupies - visually identical, structurally disconnected, and
    a mechanism as far as the solver is concerned.
    """
    if settings.to_nodes:
        existing = structure.node_at(x, y)
        if existing is not None:
            return SnapResult(existing.x, existing.y, SnapKind.NODE, node_id=existing.id)
    return SnapResult(x, y, kind)


def _nearest_node(structure: Structure, x: float, y: float, tolerance: float):  # type: ignore[no-untyped-def]
    """Closest node within tolerance, or None. Ties break on the lower id for determinism."""
    best = None
    best_distance = tolerance
    for node in structure.nodes.values():
        distance = geometry.distance(node.x, node.y, x, y)
        if distance <= best_distance:
            if best is not None and distance == best_distance and node.id > best.id:
                continue
            best = node
            best_distance = distance
    return best


def _nearest_member_point(
    structure: Structure, x: float, y: float, tolerance: float
) -> tuple[int, float, float] | None:
    """Closest point on any member within tolerance.

    Interior hits only: a projection that lands on an end is already covered by node snapping,
    and returning it here would mask the higher-priority node result.
    """
    best: tuple[int, float, float] | None = None
    best_distance = tolerance

    for member_id in sorted(structure.members):
        member = structure.members[member_id]
        node_i = structure.nodes.get(member.node_i)
        node_j = structure.nodes.get(member.node_j)
        if node_i is None or node_j is None:
            continue
        t, px, py, distance = geometry.project_point_on_segment(
            x, y, node_i.x, node_i.y, node_j.x, node_j.y
        )
        if distance <= best_distance and 0.0 < t < 1.0:
            best = (member_id, px, py)
            best_distance = distance

    return best


def _constrain_to_angle(
    ax: float, ay: float, x: float, y: float, step_degrees: float, grid_step: float
) -> tuple[float, float]:
    """Project a point onto the nearest ray of ``step_degrees`` from an anchor.

    The distance along that ray is also rounded to the grid when one is active, so a
    Shift-drag produces both a clean angle and a clean length - which is what makes it useful
    for drawing a truss rather than merely tidy.
    """
    dx, dy = x - ax, y - ay
    distance = math.hypot(dx, dy)
    if distance <= 0.0 or step_degrees <= 0.0:
        return x, y

    step = math.radians(step_degrees)
    angle = round(math.atan2(dy, dx) / step) * step

    if grid_step > 0.0:
        snapped = round(distance / grid_step) * grid_step
        if snapped > 0.0:
            distance = snapped

    return ax + distance * math.cos(angle), ay + distance * math.sin(angle)
