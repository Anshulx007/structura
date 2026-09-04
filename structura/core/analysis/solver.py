"""The linear solver.

Partition, solve, recover. One implementation serves every analysis type — only the element
formulation and the post-processing differ.

    | K_ff  K_fc |   | u_f |   | F_f |
    |            | * |     | = |     |
    | K_cf  K_cc |   | u_c |   | R_c |

with ``u_c = 0`` (support settlement is a later phase), so ``K_ff u_f = F_f`` and
``R = K_cf u_f - F_c``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.linalg import LinAlgError, cho_factor, cho_solve

from ..arrays import FloatArray
from ..model import AnalysisType, MemberState, Severity, Structure
from ..validation import Diagnostic, errors_only
from . import diagnostics, equilibrium
from .assembler import AssembledSystem, assemble, load_scale
from .dof import DOF_PER_NODE, RZ, UX, UY, DofMap, build_dof_map, is_auto_constrained_rotation
from .elements import Truss2D
from .results import (
    AnalysisError,
    AnalysisResult,
    MemberResult,
    NodeResult,
    ReactionResult,
)
from .validation import validate_for_analysis

ZERO_FORCE_RELATIVE = 1e-9
"""A member force below this fraction of the applied load scale counts as zero.

Relative rather than absolute, so a model in newtons and the same model in kilonewtons
classify their zero-force members identically.
"""


def solve(structure: Structure, load_case_id: int | None = None) -> AnalysisResult:
    """Analyse a structure and return its results.

    Raises ``AnalysisError`` when the model cannot be solved, carrying the diagnostics that
    explain why. Warnings are attached to the returned result instead.
    """
    case = (
        structure.active_load_case
        if load_case_id is None
        else structure.load_cases[load_case_id]
    )

    issues = validate_for_analysis(structure)
    blocking = errors_only(issues)
    if blocking:
        raise AnalysisError(
            f"Cannot analyse '{structure.name}': {len(blocking)} problem(s) must be fixed first.",
            issues,
        )

    dof_map = build_dof_map(structure)
    system = assemble(structure, dof_map, case)
    reference = load_scale(case)

    K_ff = system.K[np.ix_(dof_map.free, dof_map.free)]
    stability = diagnostics.inspect(K_ff, dof_map)
    issues.extend(diagnostics.to_diagnostics(stability, dof_map))

    if not stability.is_stable:
        raise AnalysisError(
            f"'{structure.name}' is unstable and cannot be analysed.", issues
        )

    displacements = _solve_displacements(system, dof_map, issues)
    reactions = _recover_reactions(structure, system, dof_map, displacements)
    members = _recover_members(structure, system, dof_map, displacements, reference)

    result = AnalysisResult(
        model_hash=structure.content_hash(),
        analysis_type=structure.analysis_type,
        load_case_id=case.id,
        load_case_name=case.name,
        solved=True,
        displacements=displacements_by_node(dof_map, displacements),
        reactions=reactions,
        members=members,
        diagnostics=issues,
        condition_number=stability.condition_number,
    )

    result.equilibrium = equilibrium.check(structure, case, reactions, reference)
    if not result.equilibrium.passed:
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "EQUILIBRIUM_FAILED",
                "Internal check failed: applied loads and reactions do not sum to zero. "
                f"{result.equilibrium.summary()}",
                hint="This indicates a bug in the solver, not a problem with your model. "
                "Please report it with the project file.",
            )
        )

    return result


def _solve_displacements(
    system: AssembledSystem, dof_map: DofMap, issues: list[Diagnostic]
) -> FloatArray:
    """Solve the free partition, leaving constrained DOFs at zero."""
    displacements = np.zeros(dof_map.n_dof, dtype=float)
    if dof_map.n_free == 0:
        return displacements

    free = dof_map.free
    K_ff = system.K[np.ix_(free, free)]
    F_f = system.F[free]

    try:
        factor = cho_factor(K_ff, lower=True, check_finite=False)
        displacements[free] = cho_solve(factor, F_f, check_finite=False)
    except (LinAlgError, ValueError):
        # Diagnostics already cleared this matrix as non-singular, so a Cholesky failure means
        # it is merely awkward rather than degenerate. A general solve handles that.
        issues.append(
            Diagnostic(
                Severity.WARNING,
                "CHOLESKY_FALLBACK",
                "The stiffness matrix is not comfortably positive definite; a general "
                "solver was used instead.",
            )
        )
        displacements[free] = np.linalg.solve(K_ff, F_f)

    if not np.all(np.isfinite(displacements)):
        raise AnalysisError("The solution contains non-finite displacements.", issues)

    return displacements


def displacements_by_node(dof_map: DofMap, displacements: FloatArray) -> dict[int, NodeResult]:
    """Regroup the global displacement vector into per-node results."""
    results: dict[int, NodeResult] = {}
    for node_id in dof_map.node_ids:
        base = dof_map.node_positions[node_id] * DOF_PER_NODE
        results[node_id] = NodeResult(
            node_id=node_id,
            ux=float(displacements[base + UX]),
            uy=float(displacements[base + UY]),
            rz=float(displacements[base + RZ]),
        )
    return results


def _recover_reactions(
    structure: Structure,
    system: AssembledSystem,
    dof_map: DofMap,
    displacements: FloatArray,
) -> dict[int, ReactionResult]:
    """``R = K u - F`` evaluated at the constrained DOFs."""
    full = system.K @ displacements - system.F

    reactions: dict[int, ReactionResult] = {}
    for node_id in sorted(structure.supports):
        if node_id not in dof_map.node_positions:
            continue
        base = dof_map.node_positions[node_id] * DOF_PER_NODE
        support = structure.supports[node_id]

        moment_index = base + RZ
        # In truss mode every rotation was auto-constrained; the value recovered there is
        # identically zero and is not a physical reaction (conventions §3).
        reports_moment = support.rz and not is_auto_constrained_rotation(
            dof_map, moment_index, structure
        )

        reactions[node_id] = ReactionResult(
            node_id=node_id,
            fx=float(full[base + UX]) if support.ux else 0.0,
            fy=float(full[base + UY]) if support.uy else 0.0,
            mz=float(full[moment_index]) if reports_moment else 0.0,
            has_moment=reports_moment,
        )
    return reactions


def _recover_members(
    structure: Structure,
    system: AssembledSystem,
    dof_map: DofMap,
    displacements: FloatArray,
    reference: float,
) -> dict[int, MemberResult]:
    """Compute internal forces for every element."""
    zero_threshold = max(ZERO_FORCE_RELATIVE * reference, 1e-12)
    results: dict[int, MemberResult] = {}

    for element in system.elements:
        member = structure.members[element.member_id]
        geo = structure.member_geometry(element.member_id)
        section = structure.section_of(member)

        fixed_end = system.fixed_end_forces.get(element.member_id)
        end_forces = element.end_forces(displacements, dof_map, fixed_end)

        # Tension positive: end_forces[0] is the force the node exerts on the member along
        # local x, which points inward for a bar being pulled.
        axial = float(-end_forces[0])

        if abs(axial) <= zero_threshold:
            state = MemberState.ZERO
            axial = 0.0
        elif axial > 0.0:
            state = MemberState.TENSION
        else:
            state = MemberState.COMPRESSION

        elongation = (
            element.elongation(displacements, dof_map)
            if isinstance(element, Truss2D)
            else 0.0
        )

        results[element.member_id] = MemberResult(
            member_id=element.member_id,
            node_i=member.node_i,
            node_j=member.node_j,
            length=geo.length,
            angle_deg=geo.angle_deg,
            axial=axial,
            state=state,
            stress=axial / section.area,
            end_forces_local=end_forces,
            elongation=elongation,
        )

    return results


def analysis_summary(result: AnalysisResult) -> str:
    """One-paragraph account of a run, for the CLI and the report header."""
    kind = "Truss" if result.analysis_type is AnalysisType.TRUSS else "Frame"
    lines = [
        f"{kind} analysis of load case '{result.load_case_name}'",
        f"  members analysed : {len(result.members)}",
        f"  supports         : {len(result.reactions)}",
        f"  max axial force  : {result.max_abs_axial:.4g} N",
        f"  max displacement : {result.max_displacement:.4g} m",
    ]
    if math.isfinite(result.condition_number):
        lines.append(f"  condition number : {result.condition_number:.3e}")
    if result.equilibrium is not None:
        lines.append(f"  {result.equilibrium.summary()}")
    return "\n".join(lines)


__all__ = ["ZERO_FORCE_RELATIVE", "AnalysisError", "analysis_summary", "solve"]
