"""Structural analysis engine.

Pure NumPy/SciPy. Knows nothing about drawing, selection or windows, which is what lets the
whole thing be validated against textbook answers before any GUI exists.

Typical use::

    from structura.core import examples
    from structura.core.analysis import solve

    result = solve(examples.t2_triangular_truss())
    print(result.member(1).axial, result.member(1).state_label)
"""

from .assembler import assemble, build_element
from .diagnostics import Mechanism, StabilityReport
from .dof import DofMap, build_dof_map
from .results import (
    AnalysisError,
    AnalysisResult,
    EquilibriumCheck,
    MemberResult,
    NodeResult,
    ReactionResult,
)
from .solver import analysis_summary, solve
from .validation import validate_for_analysis

__all__ = [
    "AnalysisError",
    "AnalysisResult",
    "DofMap",
    "EquilibriumCheck",
    "Mechanism",
    "MemberResult",
    "NodeResult",
    "ReactionResult",
    "StabilityReport",
    "analysis_summary",
    "assemble",
    "build_dof_map",
    "build_element",
    "solve",
    "validate_for_analysis",
]
