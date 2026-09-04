"""Global stiffness matrix and load vector assembly.

Dense ``float64`` throughout. For the model sizes this application targets (a few thousand
DOF) a dense factorisation is faster than a sparse one and far simpler to reason about; the
swap point is roughly 5000 DOF, at which stage this module is the only thing that changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..arrays import FloatArray
from ..model import AnalysisType, LoadCase, Structure
from .dof import DOF_PER_NODE, RZ, UX, UY, DofMap
from .elements import Element, ElementProperties, Truss2D


@dataclass(slots=True)
class AssembledSystem:
    """The linear system before boundary conditions are applied."""

    K: FloatArray
    F: FloatArray
    elements: list[Element]
    fixed_end_forces: dict[int, FloatArray] = field(default_factory=dict)
    """Per-member local fixed-end force vectors, retained for internal force recovery.

    Empty for trusses. Adding equivalent nodal loads to ``F`` without keeping these would
    leave reactions correct and mid-span bending moments wrong (conventions §5).
    """

    @property
    def n_dof(self) -> int:
        return int(self.F.size)


def build_element(structure: Structure, member_id: int) -> Element:
    """Create the element formulation matching the model's analysis type."""
    member = structure.members[member_id]
    geo = structure.member_geometry(member_id)
    material = structure.material_of(member)
    section = structure.section_of(member)

    props = ElementProperties(
        member_id=member_id,
        node_i=member.node_i,
        node_j=member.node_j,
        length=geo.length,
        cos=geo.cos,
        sin=geo.sin,
        E=material.E,
        area=section.area,
        inertia=section.inertia,
    )

    if structure.analysis_type is AnalysisType.TRUSS:
        return Truss2D(props)

    raise NotImplementedError(
        f"Analysis type {structure.analysis_type.value!r} has no element formulation yet. "
        "The frame element arrives in phase 5."
    )


def assemble(structure: Structure, dof_map: DofMap, case: LoadCase) -> AssembledSystem:
    """Build ``K`` and ``F`` for one load case."""
    n_dof = dof_map.n_dof
    K = np.zeros((n_dof, n_dof), dtype=float)
    F = np.zeros(n_dof, dtype=float)

    elements = [build_element(structure, member_id) for member_id in sorted(structure.members)]

    for element in elements:
        indices = element.dof_indices(dof_map)
        K[np.ix_(indices, indices)] += element.global_stiffness()

    _apply_nodal_loads(F, dof_map, case)

    return AssembledSystem(K=K, F=F, elements=elements)


def _apply_nodal_loads(F: FloatArray, dof_map: DofMap, case: LoadCase) -> None:
    """Scatter joint loads into the global load vector."""
    for load in case.nodal:
        if load.node_id not in dof_map.node_positions:
            continue  # dangling load; validation reports it
        base = dof_map.node_positions[load.node_id] * DOF_PER_NODE
        F[base + UX] += load.fx
        F[base + UY] += load.fy
        F[base + RZ] += load.mz


def load_scale(case: LoadCase) -> float:
    """Representative magnitude of the applied loading.

    Used as the reference for relative tolerances — zero-force detection and the equilibrium
    residual are meaningless as absolute numbers, since a model in newtons and the same model
    in kilonewtons must reach the same verdict.
    """
    magnitudes: list[float] = []
    for nodal in case.nodal:
        magnitudes.extend((abs(nodal.fx), abs(nodal.fy), abs(nodal.mz)))
    for point in case.member_point:
        magnitudes.extend((abs(point.fx), abs(point.fy)))
    for moment in case.member_moment:
        magnitudes.append(abs(moment.mz))
    for distributed in case.member_dist:
        magnitudes.extend((abs(distributed.w1), abs(distributed.w2)))
    largest = max(magnitudes, default=0.0)
    return largest if largest > 0.0 else 1.0
