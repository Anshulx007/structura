"""Two-dimensional truss (bar) element.

Four degrees of freedom — a translation pair at each end. The member carries axial force only,
so it contributes no rotational stiffness at all; that is why truss mode auto-constrains every
``rz`` DOF (see ``dof.py``).
"""

from __future__ import annotations

import numpy as np

from ...arrays import FloatArray
from ..dof import UX, UY, DofMap
from .base import Element


class Truss2D(Element):
    """Axial-only bar element with local DOF order ``[u_i, v_i, u_j, v_j]``."""

    def dof_slots(self) -> tuple[tuple[int, int], ...]:
        return (
            (self.props.node_i, UX),
            (self.props.node_i, UY),
            (self.props.node_j, UX),
            (self.props.node_j, UY),
        )

    def local_stiffness(self) -> FloatArray:
        """``EA/L`` acting along local x only; the transverse rows are identically zero."""
        k = self.props.ea_over_l
        return k * np.array(
            [
                [1.0, 0.0, -1.0, 0.0],
                [0.0, 0.0, 0.0, 0.0],
                [-1.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 0.0],
            ]
        )

    def transformation(self) -> FloatArray:
        """Rotate global translations into local axes. Local y is 90 deg CCW from local x."""
        c, s = self.props.cos, self.props.sin
        return np.array(
            [
                [c, s, 0.0, 0.0],
                [-s, c, 0.0, 0.0],
                [0.0, 0.0, c, s],
                [0.0, 0.0, -s, c],
            ]
        )

    def global_stiffness(self) -> FloatArray:
        """Closed form of ``T.T @ k @ T`` — cheaper and better conditioned than the product."""
        c, s = self.props.cos, self.props.sin
        k = self.props.ea_over_l
        cc, ss, cs = c * c, s * s, c * s
        return k * np.array(
            [
                [cc, cs, -cc, -cs],
                [cs, ss, -cs, -ss],
                [-cc, -cs, cc, cs],
                [-cs, -ss, cs, ss],
            ]
        )

    def end_forces(
        self, displacements: FloatArray, dof_map: DofMap, fixed_end: FloatArray | None = None
    ) -> FloatArray:
        """Local end forces padded to the uniform six-component layout.

        A truss element cannot carry span loads, so ``fixed_end`` must be ``None`` here; the
        validation layer rejects such loads long before assembly.
        """
        if fixed_end is not None and np.any(fixed_end):
            raise ValueError(
                f"Member {self.member_id}: a truss element cannot carry span loads. "
                "Split the member and brace the new joint, or switch to frame analysis."
            )
        local = self.local_stiffness() @ self.local_displacements(displacements, dof_map)
        return np.array([local[0], 0.0, 0.0, local[2], 0.0, 0.0])

    def axial_force(self, displacements: FloatArray, dof_map: DofMap) -> float:
        """Axial force, **tension positive** (conventions §6).

        ``end_forces[0]`` is the force the node at end i exerts on the member along local x.
        A bar in tension is pulled outward there, so that value is negative and the sign flips.
        """
        return float(-self.end_forces(displacements, dof_map)[0])

    def elongation(self, displacements: FloatArray, dof_map: DofMap) -> float:
        """Change in length. Positive means the bar got longer."""
        local = self.local_displacements(displacements, dof_map)
        return float(local[2] - local[0])
