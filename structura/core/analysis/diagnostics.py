"""Stability diagnostics.

Determinacy formulas such as ``m + r = 2j`` are necessary but not sufficient: three vertical
rollers satisfy every counting rule and still leave the structure free to slide sideways. The
authoritative test is numerical — the **null space of the free partition of the stiffness
matrix**. Every null vector is a displacement pattern that costs no strain energy, which is
precisely the definition of a mechanism.

The payoff is the error message. Instead of "singular matrix", this module can say *which
joint moves and in what direction*, and hand back the mode shape so the GUI can draw it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..arrays import FloatArray
from ..model import Severity
from ..validation import Diagnostic
from .dof import RZ, UX, UY, DofMap

SINGULARITY_RCOND = 1e-10
"""Singular values below ``rcond * largest`` count as zero.

Loose enough that a genuine mechanism (exactly zero in exact arithmetic, ~1e-16 relative in
floating point) is always caught; tight enough that a legitimately slender structure is not
mistaken for one.
"""

ILL_CONDITIONED = 1e12
"""Condition numbers above this are solvable but the answers deserve a warning."""

DOMINANCE = 0.15
"""A DOF participates in a reported mode when its component exceeds this fraction of the peak."""


@dataclass(slots=True)
class Mechanism:
    """One rigid-body or internal mechanism found in the free partition."""

    mode: FloatArray = field(repr=False)
    """Null vector expressed over the **free** DOFs."""
    singular_value: float
    participating: list[tuple[int, float]]
    """``(global dof index, component)`` for the DOFs that dominate this mode."""

    def nodes(self, dof_map: DofMap) -> list[int]:
        seen: list[int] = []
        for global_index, _ in self.participating:
            node_id, _slot = dof_map.owner(global_index)
            if node_id not in seen:
                seen.append(node_id)
        return seen

    def describe(self, dof_map: DofMap) -> str:
        """Plain-language account of what moves, and which way."""
        by_node: dict[int, dict[int, float]] = {}
        for global_index, component in self.participating:
            node_id, slot = dof_map.owner(global_index)
            by_node.setdefault(node_id, {})[slot] = component

        if not by_node:
            return "an unrestrained displacement pattern"

        uniform = self._uniform_translation(by_node)
        if uniform is not None:
            return f"the whole structure can translate freely {_heading_phrase(*uniform)}"

        if len(by_node) > 3:
            listed = ", ".join(str(n) for n in sorted(by_node)[:3])
            return f"a body movement involving nodes {listed} and {len(by_node) - 3} more"

        parts: list[str] = []
        for node_id in sorted(by_node):
            slots = by_node[node_id]
            dx, dy = slots.get(UX, 0.0), slots.get(UY, 0.0)
            if dx or dy:
                parts.append(f"node {node_id} can translate freely {_heading_phrase(dx, dy)}")
            elif RZ in slots:
                parts.append(f"node {node_id} can rotate freely")
        return "; ".join(parts) if parts else "an unrestrained displacement pattern"

    @staticmethod
    def _uniform_translation(by_node: dict[int, dict[int, float]]) -> tuple[float, float] | None:
        """Detect a rigid-body translation: every participating node moving identically.

        Worth special-casing because it is the commonest real mechanism — three parallel
        rollers, say — and "the whole structure can slide sideways" is far more useful than a
        list of node numbers.
        """
        if len(by_node) < 3:
            return None
        if any(RZ in slots for slots in by_node.values()):
            return None

        vectors = [(slots.get(UX, 0.0), slots.get(UY, 0.0)) for slots in by_node.values()]
        first = vectors[0]
        scale = max(math.hypot(dx, dy) for dx, dy in vectors)
        if scale <= 0.0:
            return None
        if any(
            math.hypot(dx - first[0], dy - first[1]) > 0.05 * scale for dx, dy in vectors[1:]
        ):
            return None
        return first


def _heading_phrase(dx: float, dy: float) -> str:
    """Describe a direction in words, preferring the axis names when it is axis-aligned."""
    if dx and not dy:
        return "in X"
    if dy and not dx:
        return "in Y"
    heading = math.degrees(math.atan2(dy, dx)) % 180.0
    return f"along {heading:.0f} deg from +X"


@dataclass(slots=True)
class StabilityReport:
    """Verdict on whether the assembled system can be solved."""

    mechanisms: list[Mechanism]
    condition_number: float
    unstiffened_dofs: list[int]
    """Free DOFs with no stiffness at all - the cheapest and clearest failure to explain."""

    @property
    def is_stable(self) -> bool:
        return not self.mechanisms and not self.unstiffened_dofs

    @property
    def is_ill_conditioned(self) -> bool:
        return math.isfinite(self.condition_number) and self.condition_number > ILL_CONDITIONED


def inspect(K_ff: FloatArray, dof_map: DofMap) -> StabilityReport:
    """Examine the free partition for mechanisms and poor conditioning."""
    if K_ff.size == 0:
        return StabilityReport(mechanisms=[], condition_number=1.0, unstiffened_dofs=[])

    free = dof_map.free
    unstiffened = [int(free[i]) for i in np.flatnonzero(~K_ff.any(axis=1))]

    singular_values = np.linalg.svd(K_ff, compute_uv=False)
    largest = float(singular_values[0]) if singular_values.size else 0.0
    smallest = float(singular_values[-1]) if singular_values.size else 0.0
    condition = largest / smallest if smallest > 0.0 else math.inf

    if largest <= 0.0:
        return StabilityReport(
            mechanisms=[],
            condition_number=math.inf,
            unstiffened_dofs=unstiffened or [int(i) for i in free],
        )

    threshold = largest * SINGULARITY_RCOND
    if smallest > threshold:
        return StabilityReport(
            mechanisms=[], condition_number=condition, unstiffened_dofs=unstiffened
        )

    # Only compute the vectors once we know there is a null space to describe.
    _u, values, vt = np.linalg.svd(K_ff)
    null_rows = np.flatnonzero(values <= threshold)

    mechanisms: list[Mechanism] = []
    for row in null_rows:
        vector = vt[row]
        peak = float(np.abs(vector).max())
        if peak <= 0.0:
            continue
        participating = [
            (int(free[i]), float(vector[i]))
            for i in np.flatnonzero(np.abs(vector) >= DOMINANCE * peak)
        ]
        mechanisms.append(
            Mechanism(
                mode=vector,
                singular_value=float(values[row]),
                participating=participating,
            )
        )

    return StabilityReport(
        mechanisms=mechanisms, condition_number=condition, unstiffened_dofs=unstiffened
    )


def to_diagnostics(report: StabilityReport, dof_map: DofMap) -> list[Diagnostic]:
    """Turn a stability report into messages a user can act on."""
    issues: list[Diagnostic] = []

    if report.unstiffened_dofs:
        by_node: dict[int, list[str]] = {}
        for global_index in report.unstiffened_dofs:
            node_id, _slot = dof_map.owner(global_index)
            by_node.setdefault(node_id, []).append(dof_map.describe(global_index))
        for node_id, names in sorted(by_node.items()):
            issues.append(
                Diagnostic(
                    Severity.ERROR,
                    "UNSTIFFENED_DOF",
                    f"Node {node_id} has no stiffness resisting {', '.join(names)} - nothing "
                    "connects it to the rest of the structure.",
                    node_ids=[node_id],
                    hint="Attach a member or add a support at this joint.",
                )
            )

    for number, mechanism in enumerate(report.mechanisms, start=1):
        issues.append(
            Diagnostic(
                Severity.ERROR,
                "MECHANISM",
                f"Mechanism {number} of {len(report.mechanisms)}: "
                f"{mechanism.describe(dof_map)}.",
                node_ids=mechanism.nodes(dof_map),
                hint="The structure is not stable: this movement costs no strain energy. "
                "Add a support or a member to restrain it.",
            )
        )

    if report.mechanisms:
        issues.append(
            Diagnostic(
                Severity.INFO,
                "MECHANISM_COUNT",
                f"The structure has {len(report.mechanisms)} independent mechanism(s). "
                "Each one needs a restraint before the structure can be analysed.",
            )
        )
    elif report.is_ill_conditioned:
        issues.append(
            Diagnostic(
                Severity.WARNING,
                "ILL_CONDITIONED",
                f"The stiffness matrix is badly conditioned "
                f"(condition number {report.condition_number:.2e}); results may be "
                "numerically unreliable.",
                hint="Look for members that are extremely short, extremely slender, or "
                "orders of magnitude stiffer than their neighbours.",
            )
        )

    return issues


__all__ = [
    "ILL_CONDITIONED",
    "SINGULARITY_RCOND",
    "Mechanism",
    "StabilityReport",
    "inspect",
    "to_diagnostics",
]
