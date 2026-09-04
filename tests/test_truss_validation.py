"""Phase 2 gate: the truss solver against closed-form textbook answers.

Every expected value here is reproducible by hand with the method of joints. Tolerances are
tight (1e-9 relative) because these are exact results, not approximations — a solver that
needs a loose tolerance to pass is a solver with a bug.
"""

from __future__ import annotations

import numpy as np
import pytest

from structura.core import examples
from structura.core.analysis import solve
from structura.core.model import MemberState

KN = 1.0e3
REL = 1e-9


def approx(value: float) -> object:
    return pytest.approx(value, rel=REL, abs=1e-6)


# ---------------------------------------------------------------- T1


def test_t1_two_bar_truss_carries_0625_p_in_tension() -> None:
    """Each bar takes P / (2 sin theta) with sin theta = 0.8, so 0.625 P."""
    result = solve(examples.t1_two_bar_truss(load_kn=10.0))

    for member in result.members.values():
        assert member.axial == approx(6.25 * KN)
        assert member.state is MemberState.TENSION
        assert member.length == approx(2.5)


def test_t1_scales_linearly_with_the_load() -> None:
    """Linear analysis: doubling the load must exactly double every force."""
    single = solve(examples.t1_two_bar_truss(load_kn=10.0))
    double = solve(examples.t1_two_bar_truss(load_kn=20.0))

    for member_id, member in single.members.items():
        assert double.member(member_id).axial == approx(2.0 * member.axial)


# ---------------------------------------------------------------- T2


def test_t2_reactions_are_ten_kn_each() -> None:
    result = solve(examples.t2_triangular_truss(load_kn=20.0))

    left, right = result.reactions[1], result.reactions[2]
    assert left.fy == approx(10.0 * KN)
    assert right.fy == approx(10.0 * KN)
    assert left.fx == approx(0.0)


def test_t2_member_forces_match_the_method_of_joints() -> None:
    """Rafters 12.5 kN compression, tie 7.5 kN tension — the canonical hand calculation."""
    result = solve(examples.t2_triangular_truss(load_kn=20.0))

    rafter_ac, rafter_bc, tie_ab = (result.member(i) for i in (1, 2, 3))

    assert rafter_ac.axial == approx(-12.5 * KN)
    assert rafter_ac.state is MemberState.COMPRESSION
    assert rafter_bc.axial == approx(-12.5 * KN)
    assert rafter_bc.state is MemberState.COMPRESSION
    assert tie_ab.axial == approx(7.5 * KN)
    assert tie_ab.state is MemberState.TENSION


def test_t2_geometry_reported_with_the_results() -> None:
    """What the member detail dialog reads: number, joints, length, angle."""
    result = solve(examples.t2_triangular_truss())
    rafter = result.member(1)

    assert (rafter.node_i, rafter.node_j) == (1, 3)
    assert rafter.length == approx(5.0)
    assert rafter.angle_deg == pytest.approx(53.13010235, rel=1e-8)

    tie = result.member(3)
    assert tie.length == approx(6.0)
    assert tie.angle_deg == approx(0.0)


def test_t2_results_are_independent_of_section_properties() -> None:
    """T2 is statically determinate, so E and A cannot change the member forces."""
    baseline = solve(examples.t2_triangular_truss())

    stiffened = examples.t2_triangular_truss()
    section = stiffened.sections[next(iter(stiffened.sections))]
    section.area *= 37.0
    stiffened.materials[next(iter(stiffened.materials))].E *= 5.0

    changed = solve(stiffened)
    for member_id, member in baseline.members.items():
        assert changed.member(member_id).axial == approx(member.axial)


def test_t2_stress_is_axial_force_over_area() -> None:
    structure = examples.t2_triangular_truss()
    area = structure.sections[next(iter(structure.sections))].area
    result = solve(structure)

    tie = result.member(3)
    assert tie.stress == approx(tie.axial / area)


# ---------------------------------------------------------------- T3


def test_t3_zero_force_member_is_detected() -> None:
    """The vertical at an unloaded T-joint carries nothing and must be classified as such."""
    result = solve(examples.t3_zero_force_member(load_kn=20.0))

    vertical = result.member(5)
    assert vertical.axial == pytest.approx(0.0, abs=1e-6)
    assert vertical.state is MemberState.ZERO
    assert len(result.zero_force_members()) == 1


def test_t3_bottom_chord_still_carries_the_tie_force() -> None:
    """Splitting the tie at midspan must not change what the tie carries."""
    result = solve(examples.t3_zero_force_member(load_kn=20.0))

    for member_id in (3, 4):
        assert result.member(member_id).axial == approx(7.5 * KN)


# ---------------------------------------------------------------- T5 (indeterminate)


def test_t5_bars_in_series_split_load_by_stiffness() -> None:
    """One degree indeterminate: AB is twice as stiff as BC, so it takes 2/3 of the load."""
    result = solve(examples.t5_bars_in_series(load_kn=30.0))

    assert result.member(1).axial == approx(20.0 * KN)
    assert result.member(1).state is MemberState.TENSION
    assert result.member(2).axial == approx(-10.0 * KN)
    assert result.member(2).state is MemberState.COMPRESSION


def test_t5_reactions_sum_to_the_applied_load() -> None:
    result = solve(examples.t5_bars_in_series(load_kn=30.0))
    total = sum(reaction.fx for reaction in result.reactions.values())
    assert total == approx(-30.0 * KN)


@pytest.mark.parametrize(("ratio", "expected_ab"), [(1.0, 2 / 3), (2.0, 0.8), (0.5, 0.5)])
def test_t5_section_properties_change_an_indeterminate_result(
    ratio: float, expected_ab: float
) -> None:
    """The counterpart to the determinate case: here E and A genuinely matter."""
    load = 30.0 * KN
    result = solve(examples.t5_bars_in_series(load_kn=30.0, area_ratio=ratio))

    assert result.member(1).axial == approx(expected_ab * load)
    assert result.member(2).axial == approx(-(1.0 - expected_ab) * load)


# ---------------------------------------------------------------- invariants


@pytest.mark.parametrize("key", ["T1", "T2", "T3", "T5"])
def test_equilibrium_holds_for_every_stable_truss(key: str) -> None:
    """The free correctness guard: loads plus reactions must sum to zero."""
    result = solve(examples.build(key))

    assert result.equilibrium is not None
    assert result.equilibrium.passed, result.equilibrium.summary()


@pytest.mark.parametrize("key", ["T1", "T2", "T3", "T5"])
def test_no_reaction_moment_is_reported_in_truss_mode(key: str) -> None:
    """Truss mode auto-constrains every rotation; those values are not physical reactions."""
    result = solve(examples.build(key))

    for reaction in result.reactions.values():
        assert not reaction.has_moment
        assert reaction.mz == 0.0


@pytest.mark.parametrize("angle_deg", [0.0, 17.0, 45.0, 90.0, 180.0, -63.5])
def test_rotating_the_whole_model_leaves_member_forces_unchanged(angle_deg: float) -> None:
    """Rotation invariance — the single most effective test for transformation-matrix bugs.

    Rotating the geometry and the loads together is a change of observer, not of physics, so
    every axial force must be identical.
    """
    baseline = solve(examples.t2_triangular_truss())

    theta = np.radians(angle_deg)
    cos, sin = np.cos(theta), np.sin(theta)

    rotated = examples.t2_triangular_truss()
    for node in rotated.nodes.values():
        node.x, node.y = node.x * cos - node.y * sin, node.x * sin + node.y * cos
    for load in rotated.active_load_case.nodal:
        load.fx, load.fy = load.fx * cos - load.fy * sin, load.fx * sin + load.fy * cos
    # Supports must rotate too; a pin is direction-free, so make both ends pins to keep the
    # restraint pattern meaningful in the rotated frame.
    from structura.core.model import Support

    for node_id in list(rotated.supports):
        rotated.set_support(Support.pin(node_id))

    # Re-solve the unrotated model with the same pinned pattern for a like-for-like baseline.
    pinned = examples.t2_triangular_truss()
    for node_id in list(pinned.supports):
        pinned.set_support(Support.pin(node_id))
    baseline = solve(pinned)

    result = solve(rotated)
    for member_id, member in baseline.members.items():
        assert result.member(member_id).axial == approx(member.axial)


def test_superposition_holds() -> None:
    """Linear analysis: solving the sum of two load cases equals summing their solutions."""
    first = examples.t2_triangular_truss(load_kn=20.0)
    second = examples.t2_triangular_truss(load_kn=0.0)
    apex = max(second.nodes, key=lambda nid: second.nodes[nid].y)
    second.active_load_case.nodal.clear()
    second.active_load_case.nodal.append(
        type(first.active_load_case.nodal[0])(apex, fx=15.0 * KN, fy=0.0, mz=0.0)
    )

    combined = examples.t2_triangular_truss(load_kn=20.0)
    combined.active_load_case.nodal.append(
        type(combined.active_load_case.nodal[0])(apex, fx=15.0 * KN, fy=0.0, mz=0.0)
    )

    a, b, both = solve(first), solve(second), solve(combined)
    for member_id in both.members:
        assert both.member(member_id).axial == approx(
            a.member(member_id).axial + b.member(member_id).axial
        )


def test_symmetric_structure_and_load_give_symmetric_results() -> None:
    result = solve(examples.t2_triangular_truss())
    assert result.member(1).axial == approx(result.member(2).axial)
    assert result.reactions[1].fy == approx(result.reactions[2].fy)


def test_displacements_are_consistent_with_member_elongation() -> None:
    """Cross-check the kinematics: elongation must equal N*L/(E*A)."""
    structure = examples.t2_triangular_truss()
    result = solve(structure)

    for member_id, member in result.members.items():
        model_member = structure.members[member_id]
        ea = structure.material_of(model_member).E * structure.section_of(model_member).area
        assert member.elongation == approx(member.axial * member.length / ea)


def test_model_hash_is_recorded_with_the_results() -> None:
    """This is what makes stale results detectable rather than silently trusted."""
    structure = examples.t2_triangular_truss()
    result = solve(structure)

    assert result.model_hash == structure.content_hash()
    assert not result.is_stale_for(structure.content_hash())

    apex = max(structure.nodes, key=lambda nid: structure.nodes[nid].y)
    structure.move_node(apex, 3.0, 5.0)
    assert result.is_stale_for(structure.content_hash())


def test_max_abs_axial_reports_the_colour_ramp_scale() -> None:
    result = solve(examples.t2_triangular_truss())
    assert result.max_abs_axial == approx(12.5 * KN)
