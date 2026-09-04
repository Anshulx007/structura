"""Element interface.

One assembler and one solver serve both analysis types; only the element formulation differs.
Every element must be able to say which global equations it touches, what its stiffness looks
like in global axes, and how to recover its internal forces from the solved displacements.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ...arrays import FloatArray, IntArray
from ..dof import DofMap


@dataclass(slots=True)
class ElementProperties:
    """Everything an element needs from the model, resolved once at assembly time."""

    member_id: int
    node_i: int
    node_j: int
    length: float
    cos: float
    sin: float
    E: float
    area: float
    inertia: float

    @property
    def ea_over_l(self) -> float:
        return self.E * self.area / self.length

    @property
    def ei(self) -> float:
        return self.E * self.inertia


class Element(ABC):
    """Base class for a 2D structural element."""

    def __init__(self, props: ElementProperties) -> None:
        self.props = props

    @property
    def member_id(self) -> int:
        return self.props.member_id

    @property
    def n_local_dof(self) -> int:
        return len(self.dof_slots())

    @abstractmethod
    def dof_slots(self) -> tuple[tuple[int, int], ...]:
        """The ``(node id, dof slot)`` pairs this element connects, in local DOF order."""

    @abstractmethod
    def local_stiffness(self) -> FloatArray:
        """Stiffness in element local axes."""

    @abstractmethod
    def transformation(self) -> FloatArray:
        """``T`` such that ``u_local = T @ u_global`` for this element's DOFs."""

    def global_stiffness(self) -> FloatArray:
        """``T.T @ k_local @ T`` — the element contribution in global axes."""
        transform = self.transformation()
        return transform.T @ self.local_stiffness() @ transform

    def dof_indices(self, dof_map: DofMap) -> IntArray:
        """Global equation numbers this element scatters into, in local DOF order."""
        return np.array(
            [dof_map.index(node_id, slot) for node_id, slot in self.dof_slots()], dtype=int
        )

    def local_displacements(self, displacements: FloatArray, dof_map: DofMap) -> FloatArray:
        """Extract and rotate this element's displacements into local axes."""
        return self.transformation() @ displacements[self.dof_indices(dof_map)]

    @abstractmethod
    def end_forces(
        self, displacements: FloatArray, dof_map: DofMap, fixed_end: FloatArray | None = None
    ) -> FloatArray:
        """Six local end forces ``[N_i, V_i, M_i, N_j, V_j, M_j]``.

        Always six components regardless of formulation, so every consumer — result tables,
        diagrams, the report — sees one uniform shape. A truss element reports zeros for the
        shear and moment slots.

        ``fixed_end`` is the element's fixed-end force vector for span loads. Omitting it
        leaves reactions correct while making mid-span bending moments wrong, so it is part of
        the interface rather than an optional extra step (conventions §5).
        """
