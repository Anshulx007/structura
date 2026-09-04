"""Enumerations shared by the model, the solver and the file format.

All members are ``str`` enums so they serialise to readable JSON without a custom encoder.
See ``docs/conventions.md`` for the meaning of every sign and direction.
"""

from __future__ import annotations

from enum import Enum


class AnalysisType(str, Enum):
    """Which element formulation the whole model uses.

    This is a property of the *model*, not of individual members: a project is either an
    ideal truss or a beam/frame. It selects the element class and switches the validation
    ruleset, but both paths share one assembler, solver and diagnostics.
    """

    TRUSS = "truss"
    """2 active DOF per node. Members carry axial force only. Nodal loads only."""

    FRAME = "frame"
    """3 DOF per node. Members carry axial force, shear and bending. Span loads allowed."""


class SupportType(str, Enum):
    """Named support configurations.

    ``ROLLER_X`` is the usual beam roller: it sits on a horizontal surface, so it is *free to
    move along X* and restrains ``uy``. ``ROLLER_Y`` leans against a vertical surface: free
    along Y, restrains ``ux``.
    """

    FREE = "free"
    PIN = "pin"
    ROLLER_X = "roller_x"
    ROLLER_Y = "roller_y"
    FIXED = "fixed"
    CUSTOM = "custom"
    """Any restraint combination that is not one of the named cases above."""


class LoadDirection(str, Enum):
    """How a distributed or member point load is oriented. See conventions §9."""

    LOCAL_PERPENDICULAR = "local_perpendicular"
    """Normal to the member, per unit member length (wind, pressure)."""

    LOCAL_AXIAL = "local_axial"
    """Along the member, per unit member length."""

    GLOBAL_Y = "global_y"
    """Along global Y, per unit member length."""

    GLOBAL_Y_PROJECTED = "global_y_projected"
    """Along global Y, per unit *horizontal* length (gravity, snow). The default."""

    GLOBAL_X = "global_x"
    """Along global X, per unit member length."""


class MemberState(str, Enum):
    """Axial state of a member after analysis."""

    TENSION = "tension"
    COMPRESSION = "compression"
    ZERO = "zero"


class Severity(str, Enum):
    """Severity of a validation or analysis diagnostic."""

    ERROR = "error"
    """Analysis cannot proceed."""

    WARNING = "warning"
    """Analysis can proceed but the result may not mean what the user expects."""

    INFO = "info"
