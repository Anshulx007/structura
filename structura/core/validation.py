"""Model integrity and geometry validation.

This module answers "is this model well-formed?" — dangling references, degenerate geometry,
loads that fall off the end of their member. It says nothing about *structural* validity;
whether the structure is stable is decided numerically by the null-space test on the assembled
stiffness matrix (see the analysis package), because determinacy formulas cannot decide it.

``Diagnostic`` is defined here because both this module and the analysis diagnostics produce
them, and the GUI shows them in one list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geometry
from .model import AnalysisType, Severity, Structure


@dataclass(slots=True)
class Diagnostic:
    """One problem found in a model or during analysis.

    ``node_ids`` / ``member_ids`` let the GUI select and zoom to the offending item when the
    user clicks the message — the difference between a useful error and an annoying one.
    """

    severity: Severity
    code: str
    message: str
    node_ids: list[int] = field(default_factory=list)
    member_ids: list[int] = field(default_factory=list)
    hint: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def __str__(self) -> str:
        prefix = self.severity.value.upper()
        suffix = f" - {self.hint}" if self.hint else ""
        return f"[{prefix}] {self.code}: {self.message}{suffix}"


def _error(code: str, message: str, **kwargs: object) -> Diagnostic:
    return Diagnostic(Severity.ERROR, code, message, **kwargs)  # type: ignore[arg-type]


def _warning(code: str, message: str, **kwargs: object) -> Diagnostic:
    return Diagnostic(Severity.WARNING, code, message, **kwargs)  # type: ignore[arg-type]


def _info(code: str, message: str, **kwargs: object) -> Diagnostic:
    return Diagnostic(Severity.INFO, code, message, **kwargs)  # type: ignore[arg-type]


def validate_model(structure: Structure) -> list[Diagnostic]:
    """Check that a model is well-formed, independent of analysis type.

    Returns every problem found rather than raising on the first, so the GUI can show a
    complete list.
    """
    issues: list[Diagnostic] = []
    issues.extend(_check_references(structure))
    issues.extend(_check_geometry(structure))
    issues.extend(_check_load_positions(structure))
    return issues


def _check_references(structure: Structure) -> list[Diagnostic]:
    """Dangling ids: members pointing at deleted nodes, loads at deleted members, etc."""
    issues: list[Diagnostic] = []

    for member in structure.members.values():
        for node_id in member.nodes:
            if node_id not in structure.nodes:
                issues.append(
                    _error(
                        "DANGLING_MEMBER_NODE",
                        f"Member {member.id} references node {node_id}, which does not exist.",
                        member_ids=[member.id],
                    )
                )
        if member.material_id not in structure.materials:
            issues.append(
                _error(
                    "MISSING_MATERIAL",
                    f"Member {member.id} references material {member.material_id}, "
                    "which does not exist.",
                    member_ids=[member.id],
                )
            )
        if member.section_id not in structure.sections:
            issues.append(
                _error(
                    "MISSING_SECTION",
                    f"Member {member.id} references section {member.section_id}, "
                    "which does not exist.",
                    member_ids=[member.id],
                )
            )

    for node_id in structure.supports:
        if node_id not in structure.nodes:
            issues.append(
                _error(
                    "DANGLING_SUPPORT",
                    f"A support references node {node_id}, which does not exist.",
                )
            )

    for case in structure.load_cases.values():
        for load in case.nodal:
            if load.node_id not in structure.nodes:
                issues.append(
                    _error(
                        "DANGLING_NODAL_LOAD",
                        f"Load case '{case.name}' has a load at node {load.node_id}, "
                        "which does not exist.",
                    )
                )
        for member_load in case.member_loads():
            if member_load.member_id not in structure.members:
                issues.append(
                    _error(
                        "DANGLING_MEMBER_LOAD",
                        f"Load case '{case.name}' has a load on member "
                        f"{member_load.member_id}, which does not exist.",
                    )
                )

    for combo in structure.combinations.values():
        for case_id in combo.factors:
            if case_id not in structure.load_cases:
                issues.append(
                    _error(
                        "DANGLING_COMBINATION",
                        f"Combination '{combo.name}' references load case {case_id}, "
                        "which does not exist.",
                    )
                )

    return issues


def _check_geometry(structure: Structure) -> list[Diagnostic]:
    """Degenerate and duplicated geometry."""
    issues: list[Diagnostic] = []

    for member in structure.members.values():
        if member.node_i not in structure.nodes or member.node_j not in structure.nodes:
            continue  # already reported as a dangling reference
        ni = structure.nodes[member.node_i]
        nj = structure.nodes[member.node_j]
        length = geometry.distance(ni.x, ni.y, nj.x, nj.y)
        if length < geometry.MIN_MEMBER_LENGTH:
            issues.append(
                _error(
                    "ZERO_LENGTH_MEMBER",
                    f"Member {member.id} has zero length - nodes {member.node_i} and "
                    f"{member.node_j} are at the same point.",
                    member_ids=[member.id],
                    node_ids=[member.node_i, member.node_j],
                    hint="Move one node or delete the member.",
                )
            )
        elif length < geometry.NODE_MERGE_TOL:
            issues.append(
                _warning(
                    "VERY_SHORT_MEMBER",
                    f"Member {member.id} is only {length:.2e} m long, below the "
                    f"{geometry.NODE_MERGE_TOL} m joint tolerance.",
                    member_ids=[member.id],
                    hint="Very short members make the stiffness matrix badly conditioned.",
                )
            )

    for first, second in structure.duplicate_members():
        issues.append(
            _error(
                "DUPLICATE_MEMBER",
                f"Members {first} and {second} both connect the same pair of nodes.",
                member_ids=[first, second],
                hint="Delete one of them - duplicates double the stiffness of that connection.",
            )
        )

    coincident = _coincident_nodes(structure)
    for a, b in coincident:
        issues.append(
            _warning(
                "COINCIDENT_NODES",
                f"Nodes {a} and {b} are at the same location within the joint tolerance.",
                node_ids=[a, b],
                hint="They are separate joints and will not transfer force to each other.",
            )
        )

    for node_id in structure.orphan_nodes():
        issues.append(
            _info(
                "ORPHAN_NODE",
                f"Node {node_id} is not attached to any member.",
                node_ids=[node_id],
            )
        )

    return issues


def _coincident_nodes(structure: Structure) -> list[tuple[int, int]]:
    """Pairs of distinct nodes within the merge tolerance of each other."""
    ordered = sorted(structure.nodes.values(), key=lambda n: n.id)
    pairs: list[tuple[int, int]] = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if geometry.points_coincide(first.x, first.y, second.x, second.y):
                pairs.append((first.id, second.id))
    return pairs


def _check_load_positions(structure: Structure) -> list[Diagnostic]:
    """Span loads must lie inside their member.

    This is how a geometry edit that invalidates a load gets caught: shortening a member so a
    point load now sits beyond its end is an error, not something to silently clamp.
    """
    issues: list[Diagnostic] = []

    for case in structure.load_cases.values():
        for load in case.member_loads():
            if load.member_id not in structure.members:
                continue
            member = structure.members[load.member_id]
            if member.node_i not in structure.nodes or member.node_j not in structure.nodes:
                continue
            try:
                length = structure.member_length(load.member_id)
            except ValueError:
                continue

            positions: list[tuple[str, float]] = []
            if hasattr(load, "a"):
                positions.append(("a", load.a))
            end = getattr(load, "b", None)
            if end is not None:
                positions.append(("b", float(end)))

            for name, value in positions:
                if value < -1e-12 or value > length + 1e-9:
                    issues.append(
                        _error(
                            "LOAD_OUTSIDE_MEMBER",
                            f"Load case '{case.name}': a load on member {load.member_id} has "
                            f"{name} = {value:.4g} m, outside the member length "
                            f"{length:.4g} m.",
                            member_ids=[load.member_id],
                            hint="Move the load or restore the member geometry.",
                        )
                    )

            span_end = getattr(load, "b", None)
            if span_end is not None and float(span_end) <= load.a + 1e-12:
                issues.append(
                    _error(
                        "EMPTY_LOAD_SPAN",
                        f"Load case '{case.name}': a distributed load on member "
                        f"{load.member_id} has b <= a ({span_end:.4g} <= {load.a:.4g}).",
                        member_ids=[load.member_id],
                    )
                )

    return issues


def errors_only(issues: list[Diagnostic]) -> list[Diagnostic]:
    """Filter to blocking problems."""
    return [issue for issue in issues if issue.is_error]


def describe(issues: list[Diagnostic]) -> str:
    """Render a diagnostic list for the CLI or an exception message."""
    if not issues:
        return "No problems found."
    return "\n".join(str(issue) for issue in issues)


def assert_valid(structure: Structure) -> None:
    """Raise ``ValueError`` if the model has any blocking problem. Used by save and by tests."""
    errors = errors_only(validate_model(structure))
    if errors:
        raise ValueError("Model is not well-formed:\n" + describe(errors))


__all__ = [
    "AnalysisType",
    "Diagnostic",
    "assert_valid",
    "describe",
    "errors_only",
    "validate_model",
]
