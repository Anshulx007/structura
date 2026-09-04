"""Result containers.

Every number the user ever sees comes out of one of these. The GUI performs no arithmetic on
forces: if a value is displayed, it was computed here.

``model_hash`` is what stops stale results being shown as current. When it no longer matches
the structure on screen, the overlays must grey out instead of reporting numbers that describe
a drawing the user has since edited.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..arrays import FloatArray
from ..model import AnalysisType, MemberState
from ..validation import Diagnostic


@dataclass(slots=True)
class NodeResult:
    """Displacements at a joint, in global axes (metres, radians)."""

    node_id: int
    ux: float
    uy: float
    rz: float

    @property
    def translation_magnitude(self) -> float:
        return float(np.hypot(self.ux, self.uy))


@dataclass(slots=True)
class ReactionResult:
    """Support reaction in global axes: the force the support exerts on the structure.

    ``has_moment`` is False in truss mode, where the rotational DOF was auto-constrained and
    its recovered value is identically zero rather than a physical reaction (conventions §3).
    Consumers must not display ``mz`` when this is False.
    """

    node_id: int
    fx: float
    fy: float
    mz: float
    has_moment: bool = True

    @property
    def magnitude(self) -> float:
        return float(np.hypot(self.fx, self.fy))


@dataclass(slots=True)
class MemberResult:
    """Everything known about one member after analysis.

    This is what the member detail dialog reads: number, connected joints, length, angle,
    axial force and whether it is in tension or compression.
    """

    member_id: int
    node_i: int
    node_j: int
    length: float
    angle_deg: float
    axial: float
    """Axial force, **tension positive** (conventions §6)."""
    state: MemberState
    stress: float
    """Axial stress in Pa. Positive is tensile."""
    end_forces_local: FloatArray = field(repr=False)
    """Always six components ``[N_i, V_i, M_i, N_j, V_j, M_j]``, zero-padded for trusses."""
    elongation: float = 0.0

    @property
    def is_tension(self) -> bool:
        return self.state is MemberState.TENSION

    @property
    def is_compression(self) -> bool:
        return self.state is MemberState.COMPRESSION

    @property
    def is_zero_force(self) -> bool:
        return self.state is MemberState.ZERO

    @property
    def state_label(self) -> str:
        return {
            MemberState.TENSION: "Tension",
            MemberState.COMPRESSION: "Compression",
            MemberState.ZERO: "Zero-force",
        }[self.state]


@dataclass(slots=True)
class EquilibriumCheck:
    """Post-solve self-check: applied loads plus reactions must sum to zero.

    Run on every analysis. It costs nothing and catches assembly, transformation and reaction
    recovery mistakes that a plausible-looking set of numbers would otherwise hide.
    """

    sum_fx: float
    sum_fy: float
    sum_moment: float
    reference_force: float
    tolerance: float

    @property
    def residual(self) -> float:
        return float(max(abs(self.sum_fx), abs(self.sum_fy)))

    @property
    def passed(self) -> bool:
        force_ok = self.residual <= self.tolerance
        moment_ok = abs(self.sum_moment) <= self.tolerance * max(1.0, self.reference_force)
        return force_ok and moment_ok

    def summary(self) -> str:
        verdict = "OK" if self.passed else "FAILED"
        return (
            f"Equilibrium {verdict}: "
            f"sum Fx = {self.sum_fx:.3e} N, "
            f"sum Fy = {self.sum_fy:.3e} N, "
            f"sum M = {self.sum_moment:.3e} N.m"
        )


@dataclass
class AnalysisResult:
    """The complete outcome of one analysis run."""

    model_hash: str
    analysis_type: AnalysisType
    load_case_id: int
    load_case_name: str
    solved: bool
    displacements: dict[int, NodeResult] = field(default_factory=dict)
    reactions: dict[int, ReactionResult] = field(default_factory=dict)
    members: dict[int, MemberResult] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    equilibrium: EquilibriumCheck | None = None
    condition_number: float = float("nan")

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.is_error]

    @property
    def max_abs_axial(self) -> float:
        """Largest member force magnitude — the scale for colour ramps and label sizing."""
        if not self.members:
            return 0.0
        return max(abs(m.axial) for m in self.members.values())

    @property
    def max_displacement(self) -> float:
        if not self.displacements:
            return 0.0
        return max(d.translation_magnitude for d in self.displacements.values())

    def member(self, member_id: int) -> MemberResult:
        return self.members[member_id]

    def is_stale_for(self, model_hash: str) -> bool:
        """True when the model has changed since these results were computed."""
        return self.model_hash != model_hash

    def tension_members(self) -> list[MemberResult]:
        return [m for m in self.members.values() if m.is_tension]

    def compression_members(self) -> list[MemberResult]:
        return [m for m in self.members.values() if m.is_compression]

    def zero_force_members(self) -> list[MemberResult]:
        return [m for m in self.members.values() if m.is_zero_force]


class AnalysisError(Exception):
    """Raised when analysis cannot proceed. Carries the diagnostics explaining why."""

    def __init__(self, message: str, diagnostics: list[Diagnostic] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []

    def detail(self) -> str:
        lines = [str(self)]
        lines.extend(f"  {d}" for d in self.diagnostics)
        return "\n".join(lines)
