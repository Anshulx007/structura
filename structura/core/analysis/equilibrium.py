"""Post-solve equilibrium self-check.

Applied loads plus support reactions must sum to zero in every direction, and their moments
must sum to zero about any point. This is run on **every** analysis: it costs one pass over
the loads, and it catches assembly, transformation and reaction-recovery mistakes that would
otherwise hide behind a plausible-looking set of numbers.

The check is relative, not absolute: the same structure expressed in newtons and in
kilonewtons must reach the same verdict.
"""

from __future__ import annotations

from ..model import LoadCase, LoadDirection, MemberDistLoad, Structure
from .results import EquilibriumCheck, ReactionResult

RELATIVE_TOLERANCE = 1e-6


def check(
    structure: Structure,
    case: LoadCase,
    reactions: dict[int, ReactionResult],
    reference_force: float,
) -> EquilibriumCheck:
    """Sum applied loads and reactions; the totals should be zero.

    Moments are taken about the model's bounding-box centre rather than the origin, so a
    structure drawn far from (0, 0) does not inflate the residual with large lever arms.
    """
    xmin, ymin, xmax, ymax = structure.bounds()
    px, py = 0.5 * (xmin + xmax), 0.5 * (ymin + ymax)

    sum_fx = 0.0
    sum_fy = 0.0
    sum_moment = 0.0

    for nodal in case.nodal:
        node = structure.nodes.get(nodal.node_id)
        if node is None:
            continue
        sum_fx += nodal.fx
        sum_fy += nodal.fy
        sum_moment += nodal.mz + (node.x - px) * nodal.fy - (node.y - py) * nodal.fx

    for distributed in case.member_dist:
        if distributed.member_id not in structure.members:
            continue
        fx, fy, moment = _resultant_of_distributed_load(structure, distributed, px, py)
        sum_fx += fx
        sum_fy += fy
        sum_moment += moment

    for point_load in case.member_point:
        if point_load.member_id not in structure.members:
            continue
        x, y = _point_on_member(structure, point_load.member_id, point_load.a)
        sum_fx += point_load.fx
        sum_fy += point_load.fy
        sum_moment += (x - px) * point_load.fy - (y - py) * point_load.fx

    for applied_moment in case.member_moment:
        if applied_moment.member_id in structure.members:
            sum_moment += applied_moment.mz

    for node_id, reaction in reactions.items():
        node = structure.nodes.get(node_id)
        if node is None:
            continue
        sum_fx += reaction.fx
        sum_fy += reaction.fy
        sum_moment += (node.x - px) * reaction.fy - (node.y - py) * reaction.fx
        if reaction.has_moment:
            sum_moment += reaction.mz

    return EquilibriumCheck(
        sum_fx=sum_fx,
        sum_fy=sum_fy,
        sum_moment=sum_moment,
        reference_force=reference_force,
        tolerance=RELATIVE_TOLERANCE * max(reference_force, 1.0),
    )


def _point_on_member(structure: Structure, member_id: int, a: float) -> tuple[float, float]:
    """Global coordinates of a point at local distance ``a`` from node i."""
    geo = structure.member_geometry(member_id)
    return geo.xi + geo.cos * a, geo.yi + geo.sin * a


def _resultant_of_distributed_load(
    structure: Structure, load: MemberDistLoad, px: float, py: float
) -> tuple[float, float, float]:
    """Total force and moment of a distributed load, resolved per its ``LoadDirection``.

    Phase 2 solves trusses only, where span loads are rejected before assembly, so this exists
    to keep the equilibrium check honest once the frame element lands. It integrates the
    trapezoidal intensity in closed form rather than sampling.
    """
    geo = structure.member_geometry(load.member_id)
    start, end = load.extent(geo.length)
    span = max(end - start, 0.0)
    if span <= 0.0:
        return 0.0, 0.0, 0.0

    # Trapezoid: total = mean intensity * span. Returning early on a zero resultant also
    # guarantees (w1 + w2) != 0 below, so the centroid division is safe.
    total = 0.5 * (load.w1 + load.w2) * span
    if total == 0.0:
        return 0.0, 0.0, 0.0
    centroid = start + span * (load.w1 + 2.0 * load.w2) / (3.0 * (load.w1 + load.w2))

    if load.direction is LoadDirection.GLOBAL_Y_PROJECTED:
        # Intensity is per unit horizontal length, so the member's projection sets the total.
        total *= abs(geo.cos)
        fx, fy = 0.0, total
    elif load.direction is LoadDirection.GLOBAL_Y:
        fx, fy = 0.0, total
    elif load.direction is LoadDirection.GLOBAL_X:
        fx, fy = total, 0.0
    elif load.direction is LoadDirection.LOCAL_AXIAL:
        fx, fy = total * geo.cos, total * geo.sin
    else:  # LOCAL_PERPENDICULAR — local y is 90 deg CCW from local x
        fx, fy = -total * geo.sin, total * geo.cos

    x = geo.xi + geo.cos * centroid
    y = geo.yi + geo.sin * centroid
    return fx, fy, (x - px) * fy - (y - py) * fx


__all__ = ["RELATIVE_TOLERANCE", "check"]
