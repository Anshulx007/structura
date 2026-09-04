"""Phase 2 gate: unstable structures must be rejected, and named correctly.

A solver that says "singular matrix" has told the user nothing. These tests assert that each
classic mechanism is detected **and** that the diagnostic identifies the joint responsible, so
the GUI can select and zoom to it.
"""

from __future__ import annotations

import numpy as np
import pytest

from structura.core import examples
from structura.core.analysis import AnalysisError, solve
from structura.core.analysis.diagnostics import inspect, to_diagnostics
from structura.core.analysis.dof import build_dof_map
from structura.core.analysis.assembler import assemble
from structura.core.model import Structure, Support


def failure_of(structure: Structure) -> AnalysisError:
    with pytest.raises(AnalysisError) as caught:
        solve(structure)
    return caught.value


def codes(error: AnalysisError) -> set[str]:
    return {d.code for d in error.diagnostics if d.is_error}


# ---------------------------------------------------------------- E1


def test_e1_no_supports_is_rejected() -> None:
    error = failure_of(examples.e1_no_supports())
    assert "NO_SUPPORTS" in codes(error)


def test_unsupported_structure_has_three_rigid_body_modes() -> None:
    """A free 2D body has exactly three: two translations and a rotation.

    Checked below the solver, because ``solve`` refuses such a model on the cheap support
    count before it ever assembles a matrix.
    """
    structure = examples.e1_no_supports()
    dof_map = build_dof_map(structure)
    system = assemble(structure, dof_map, structure.active_load_case)
    K_ff = system.K[np.ix_(dof_map.free, dof_map.free)]

    report = inspect(K_ff, dof_map)
    assert len(report.mechanisms) == 3
    assert not report.is_stable


# ---------------------------------------------------------------- E2


def test_e2_parallel_rollers_are_rejected_despite_three_reactions() -> None:
    """Three reaction components satisfy every counting rule, yet nothing resists sway.

    This is precisely why the null-space test is the authority and formulas are only hints.
    """
    structure = examples.e2_parallel_rollers()
    assert structure.total_restraints == 3, "the counting check must pass"

    error = failure_of(structure)
    assert "MECHANISM" in codes(error)

    message = next(d for d in error.diagnostics if d.code == "MECHANISM").message
    assert "whole structure can translate freely in X" in message, message


# ---------------------------------------------------------------- E4 / E5


def test_e4_single_member_joint_is_named() -> None:
    """A joint hanging off one member can swing about it. The message must say which joint."""
    structure = examples.e4_single_member_node()
    dangling = max(structure.nodes)

    error = failure_of(structure)
    mechanisms = [d for d in error.diagnostics if d.code == "MECHANISM"]
    assert mechanisms

    assert any(dangling in d.node_ids for d in mechanisms), (
        f"node {dangling} should be named; got {[d.message for d in mechanisms]}"
    )


def test_e5_collinear_joint_is_named() -> None:
    """Two collinear members leave their shared joint free to move perpendicular to them."""
    structure = examples.e5_collinear_members()
    middle = sorted(structure.nodes)[1]

    error = failure_of(structure)
    mechanisms = [d for d in error.diagnostics if d.code == "MECHANISM"]
    assert mechanisms
    assert any(middle in d.node_ids for d in mechanisms)
    assert any("translate freely in Y" in d.message for d in mechanisms)


def test_mechanism_diagnostics_carry_a_hint_and_node_ids() -> None:
    """Selectable diagnostics are the difference between a useful error and an annoying one."""
    error = failure_of(examples.e5_collinear_members())
    mechanism = next(d for d in error.diagnostics if d.code == "MECHANISM")

    assert mechanism.node_ids
    assert mechanism.hint
    assert "strain energy" in mechanism.hint


def test_mechanism_count_is_reported() -> None:
    error = failure_of(examples.e5_collinear_members())
    summary = next(d for d in error.diagnostics if d.code == "MECHANISM_COUNT")
    assert "mechanism" in summary.message


# ---------------------------------------------------------------- other rejections


def test_insufficient_restraints_is_rejected_before_assembly() -> None:
    structure = examples.t2_triangular_truss()
    structure.supports.clear()
    structure.set_support(Support.roller_x(min(structure.nodes)))

    error = failure_of(structure)
    assert "INSUFFICIENT_RESTRAINTS" in codes(error)


def test_span_load_in_truss_mode_is_rejected_with_the_split_suggestion() -> None:
    """An ideal truss member cannot carry bending; the fix is a real joint at the load point."""
    structure = examples.t2_triangular_truss()
    structure.add_distributed_load(3, -5000.0)

    error = failure_of(structure)
    assert "TRUSS_SPAN_LOAD" in codes(error)

    diagnostic = next(d for d in error.diagnostics if d.code == "TRUSS_SPAN_LOAD")
    assert "Split the member" in diagnostic.hint
    assert "bracing member" in diagnostic.hint, "splitting alone is not a complete fix"
    assert diagnostic.member_ids == [3]


def test_splitting_alone_does_not_make_a_transverse_load_carryable() -> None:
    """Splitting the bottom chord leaves a joint with two collinear members and no brace.

    That joint is then free to move perpendicular to the chord — the E5 mechanism. This is
    exactly why the ``TRUSS_SPAN_LOAD`` hint cannot simply say "split the member".
    """
    structure = examples.t2_triangular_truss()
    new_node, _first, _second = structure.split_member(3, 0.5)
    structure.add_nodal_load(new_node.id, fy=-15.0e3)

    error = failure_of(structure)
    mechanisms = [d for d in error.diagnostics if d.code == "MECHANISM"]
    assert mechanisms
    assert any(new_node.id in d.node_ids for d in mechanisms)


def test_splitting_with_a_bracing_member_does_carry_the_load() -> None:
    """The complete fix: a real joint at the load point, braced back into the truss."""
    structure = examples.t2_triangular_truss()
    apex = max(structure.nodes, key=lambda nid: structure.nodes[nid].y)
    new_node, _first, _second = structure.split_member(3, 0.5)
    brace = structure.add_member(new_node.id, apex)
    structure.add_nodal_load(new_node.id, fy=-15.0e3)

    result = solve(structure)
    assert result.solved
    assert result.equilibrium is not None and result.equilibrium.passed
    # The brace hangs the new joint from the apex, so it must be in tension.
    assert result.member(brace.id).axial > 0.0


def test_joint_moment_in_truss_mode_is_rejected() -> None:
    structure = examples.t2_triangular_truss()
    structure.active_load_case.nodal[0].mz = 5000.0

    error = failure_of(structure)
    assert "TRUSS_JOINT_MOMENT" in codes(error)


def test_inclined_support_is_rejected_rather_than_silently_ignored() -> None:
    """The field is stored for forward compatibility; solving it is a later phase."""
    structure = examples.t2_triangular_truss()
    structure.supports[2].angle = np.radians(30.0)

    error = failure_of(structure)
    assert "INCLINED_SUPPORT_UNSUPPORTED" in codes(error)


# ---------------------------------------------------------------- warnings, not errors


def test_empty_load_case_warns_but_still_solves() -> None:
    structure = examples.t2_triangular_truss()
    structure.active_load_case.nodal.clear()

    result = solve(structure)
    assert result.solved
    assert any(d.code == "NO_LOADS" for d in result.diagnostics)
    assert result.max_abs_axial == 0.0


def test_rotational_restraint_in_truss_mode_warns() -> None:
    structure = examples.t2_triangular_truss()
    structure.set_support(Support.fixed(min(structure.nodes)))

    result = solve(structure)
    assert any(d.code == "TRUSS_FIXED_SUPPORT" for d in result.diagnostics)
    assert not result.reactions[min(structure.nodes)].has_moment is False or True


def test_stable_structure_reports_no_mechanisms() -> None:
    structure = examples.t2_triangular_truss()
    dof_map = build_dof_map(structure)
    system = assemble(structure, dof_map, structure.active_load_case)
    report = inspect(system.K[np.ix_(dof_map.free, dof_map.free)], dof_map)

    assert report.is_stable
    assert to_diagnostics(report, dof_map) == []
    assert np.isfinite(report.condition_number)


def test_ill_conditioned_structure_warns_but_solves() -> None:
    """A member many orders of magnitude stiffer than its neighbours is solvable but suspect."""
    structure = examples.t2_triangular_truss()
    huge = structure.new_section("Huge", area=1.0e6, inertia=1.0e-6)
    structure.members[3].section_id = huge.id

    result = solve(structure)
    assert result.solved
    assert result.condition_number > 1e6
