"""Analysis-type validation: rules that depend on whether the model is a truss or a frame.

Model *well-formedness* is checked in ``structura.core.validation``. This module adds the
rules that only make sense once you know which element formulation will be used — chiefly
that an ideal truss cannot carry span loads or joint moments.

These are cheap, friendly pre-checks. They are deliberately **not** the authority on
stability: three reaction components can still be a mechanism, and a counting formula cannot
tell. That verdict comes from the null-space test in ``diagnostics.py``.
"""

from __future__ import annotations

from ..model import AnalysisType, Severity, Structure
from ..validation import Diagnostic, validate_model


def validate_for_analysis(structure: Structure) -> list[Diagnostic]:
    """Every problem that would stop or mislead an analysis of this model."""
    issues = validate_model(structure)
    issues.extend(_check_supports(structure))
    if structure.analysis_type is AnalysisType.TRUSS:
        issues.extend(_check_truss_rules(structure))
    issues.extend(_check_load_case(structure))
    return issues


def _check_supports(structure: Structure) -> list[Diagnostic]:
    """Restraint counting and support features not yet implemented."""
    issues: list[Diagnostic] = []
    total = structure.total_restraints

    if total == 0:
        issues.append(
            Diagnostic(
                Severity.ERROR,
                "NO_SUPPORTS",
                "The structure has no supports, so it is free to move as a rigid body.",
                hint="Add at least a pin and a roller (three reaction components in 2D).",
            )
        )
    elif total < 3:
        issues.append(
            Diagnostic(
                Severity.ERROR,
                "INSUFFICIENT_RESTRAINTS",
                f"Only {total} reaction component(s) are defined; a 2D structure needs at "
                "least 3 to be stable.",
                node_ids=sorted(structure.supports),
                hint="A pin gives 2, a roller 1, a fixed support 3.",
            )
        )

    for node_id, support in structure.supports.items():
        if support.is_inclined:
            issues.append(
                Diagnostic(
                    Severity.ERROR,
                    "INCLINED_SUPPORT_UNSUPPORTED",
                    f"Node {node_id} has an inclined support ({support.angle_deg:.1f} deg), "
                    "which this build cannot solve yet.",
                    node_ids=[node_id],
                    hint="Set the support angle to zero, or wait for inclined-roller support.",
                )
            )

    if structure.analysis_type is AnalysisType.TRUSS:
        for node_id, support in structure.supports.items():
            if support.rz:
                issues.append(
                    Diagnostic(
                        Severity.WARNING,
                        "TRUSS_FIXED_SUPPORT",
                        f"Node {node_id} has a rotational restraint, which has no effect in "
                        "truss analysis - truss joints are pins.",
                        node_ids=[node_id],
                        hint="Use a pin, or switch the model to frame analysis.",
                    )
                )

    return issues


def _check_truss_rules(structure: Structure) -> list[Diagnostic]:
    """Rules specific to ideal truss analysis."""
    issues: list[Diagnostic] = []

    for member in structure.members.values():
        if member.has_releases:
            issues.append(
                Diagnostic(
                    Severity.WARNING,
                    "TRUSS_RELEASE_IGNORED",
                    f"Member {member.id} has end releases, which have no meaning in truss "
                    "analysis - every truss joint is already a pin.",
                    member_ids=[member.id],
                )
            )

    case = structure.active_load_case

    for span_load in case.member_loads():
        issues.append(
            Diagnostic(
                Severity.ERROR,
                "TRUSS_SPAN_LOAD",
                f"Member {span_load.member_id} carries a load applied along its span, which "
                "an ideal truss member cannot resist - such a load causes bending.",
                member_ids=[span_load.member_id],
                hint="Split the member to create a real joint at the load point - but that "
                "joint also needs a bracing member, or it will be free to move "
                "perpendicular to the split member. Otherwise switch to frame analysis.",
            )
        )

    for nodal in case.nodal:
        if nodal.mz != 0.0:
            issues.append(
                Diagnostic(
                    Severity.ERROR,
                    "TRUSS_JOINT_MOMENT",
                    f"A moment is applied at node {nodal.node_id}, but a pinned truss joint "
                    "cannot transmit one.",
                    node_ids=[nodal.node_id],
                    hint="Replace it with a force couple at two joints, or switch to frame "
                    "analysis.",
                )
            )

    for node_id in structure.unstable_truss_nodes():
        degree = structure.node_degree(node_id)
        if degree == 0:
            continue  # reported as an orphan node by model validation
        if degree == 1:
            message = (
                f"Node {node_id} has only one member attached and is not restrained, so it "
                "is free to swing about that member."
            )
        else:
            message = (
                f"Node {node_id} is unrestrained and all its members lie on one line, so it "
                "is free to move perpendicular to them."
            )
        issues.append(
            Diagnostic(
                Severity.WARNING,
                "TRUSS_JOINT_MECHANISM",
                message,
                node_ids=[node_id],
                hint="Add a member or a support at this joint.",
            )
        )

    return issues


def _check_load_case(structure: Structure) -> list[Diagnostic]:
    """Nothing to solve for is worth saying out loud rather than returning silent zeros."""
    case = structure.active_load_case
    if case.is_empty:
        return [
            Diagnostic(
                Severity.WARNING,
                "NO_LOADS",
                f"Load case '{case.name}' contains no loads; every result will be zero.",
                hint="Apply a load before analysing.",
            )
        ]
    return []


__all__ = ["validate_for_analysis"]
