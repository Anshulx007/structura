"""Degree-of-freedom bookkeeping.

Every node owns three DOFs in the order ``(ux, uy, rz)``; the node occupying 0-based position
``n`` claims global indices ``3n``, ``3n+1``, ``3n+2`` (conventions §3).

Node **position** is not node **id**: ids are stable and sparse, positions are dense and
assigned here. Nothing outside this module may assume a relationship between the two.

Truss mode is handled by auto-constraining every rotational DOF. Truss elements contribute no
rotational stiffness, so those rows and columns would otherwise be identically zero and the
matrix singular — the classic beginner trap that reads as "your structure is unstable".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..arrays import BoolArray, IntArray
from ..model import AnalysisType, Structure

UX, UY, RZ = 0, 1, 2
DOF_PER_NODE = 3
DOF_NAMES = ("ux", "uy", "rz")


@dataclass(slots=True)
class DofMap:
    """Maps ``(node id, dof slot)`` to a global equation number and partitions free/constrained."""

    node_positions: dict[int, int]
    node_ids: list[int]
    constrained: IntArray
    free: IntArray
    auto_constrained_rotations: bool
    _restrained_mask: BoolArray = field(repr=False)

    @property
    def n_dof(self) -> int:
        return len(self.node_ids) * DOF_PER_NODE

    @property
    def n_free(self) -> int:
        return int(self.free.size)

    @property
    def n_constrained(self) -> int:
        return int(self.constrained.size)

    def index(self, node_id: int, slot: int) -> int:
        """Global equation number for one DOF of one node."""
        return self.node_positions[node_id] * DOF_PER_NODE + slot

    def node_indices(self, node_id: int) -> tuple[int, int, int]:
        """The three global indices belonging to a node, in ``(ux, uy, rz)`` order."""
        base = self.node_positions[node_id] * DOF_PER_NODE
        return base, base + 1, base + 2

    def translation_indices(self, node_id: int) -> tuple[int, int]:
        """Just ``(ux, uy)`` — what a truss element connects to."""
        base = self.node_positions[node_id] * DOF_PER_NODE
        return base, base + 1

    def owner(self, global_index: int) -> tuple[int, int]:
        """Inverse lookup: ``(node id, dof slot)`` for a global equation number."""
        position, slot = divmod(global_index, DOF_PER_NODE)
        return self.node_ids[position], slot

    def describe(self, global_index: int) -> str:
        """Human-readable name for a DOF, e.g. ``"node 7 uy"``.

        Diagnostics are only as useful as this function: it is what turns a singular matrix
        into "node 7 is free to move vertically".
        """
        node_id, slot = self.owner(global_index)
        return f"node {node_id} {DOF_NAMES[slot]}"

    def is_restrained(self, global_index: int) -> bool:
        return bool(self._restrained_mask[global_index])


def build_dof_map(structure: Structure) -> DofMap:
    """Number the DOFs of a structure and split them into free and constrained sets."""
    node_ids = sorted(structure.nodes)
    positions = {node_id: position for position, node_id in enumerate(node_ids)}
    n_dof = len(node_ids) * DOF_PER_NODE

    restrained = np.zeros(n_dof, dtype=bool)

    for node_id, support in structure.supports.items():
        if node_id not in positions:
            continue  # dangling support; model validation reports it separately
        base = positions[node_id] * DOF_PER_NODE
        restrained[base + UX] |= support.ux
        restrained[base + UY] |= support.uy
        restrained[base + RZ] |= support.rz

    auto_rotations = structure.analysis_type is AnalysisType.TRUSS
    if auto_rotations:
        restrained[RZ::DOF_PER_NODE] = True

    free = np.flatnonzero(~restrained)
    constrained = np.flatnonzero(restrained)

    return DofMap(
        node_positions=positions,
        node_ids=node_ids,
        constrained=constrained,
        free=free,
        auto_constrained_rotations=auto_rotations,
        _restrained_mask=restrained,
    )


def is_auto_constrained_rotation(dof_map: DofMap, global_index: int, structure: Structure) -> bool:
    """True when a DOF is restrained only because truss mode locked every rotation.

    The value recovered at such a DOF is identically zero and is **not** a physical reaction
    moment. It must never be shown to the user (conventions §3).
    """
    if not dof_map.auto_constrained_rotations:
        return False
    node_id, slot = dof_map.owner(global_index)
    if slot != RZ:
        return False
    support = structure.supports.get(node_id)
    return support is None or not support.rz
