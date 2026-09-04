"""Support / boundary condition."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .enums import SupportType


@dataclass(slots=True)
class Support:
    """Restraints applied at a node.

    Each flag is ``True`` when that DOF is *restrained*. The DOF order matches conventions §3:
    ``ux`` (global X), ``uy`` (global Y), ``rz`` (rotation, CCW).

    ``angle`` rotates the restraint directions — an inclined roller. It is stored from the
    start so files remain forward-compatible, but the solver only honours it from Phase 9;
    until then a non-zero angle is rejected by validation rather than silently ignored.
    """

    node_id: int
    ux: bool = False
    uy: bool = False
    rz: bool = False
    angle: float = 0.0
    """Restraint orientation in radians, CCW from global X. Zero for axis-aligned supports."""

    # -- named constructors --------------------------------------------------

    @classmethod
    def pin(cls, node_id: int) -> Support:
        """Hinge: both translations restrained, free to rotate."""
        return cls(node_id, ux=True, uy=True, rz=False)

    @classmethod
    def roller_x(cls, node_id: int) -> Support:
        """Roller on a horizontal surface: free along X, vertical restrained."""
        return cls(node_id, ux=False, uy=True, rz=False)

    @classmethod
    def roller_y(cls, node_id: int) -> Support:
        """Roller against a vertical surface: free along Y, horizontal restrained."""
        return cls(node_id, ux=True, uy=False, rz=False)

    @classmethod
    def fixed(cls, node_id: int) -> Support:
        """Encastre: all three DOFs restrained."""
        return cls(node_id, ux=True, uy=True, rz=True)

    @classmethod
    def from_type(cls, node_id: int, kind: SupportType, angle: float = 0.0) -> Support:
        builders: dict[SupportType, Callable[[int], Support]] = {
            SupportType.PIN: cls.pin,
            SupportType.ROLLER_X: cls.roller_x,
            SupportType.ROLLER_Y: cls.roller_y,
            SupportType.FIXED: cls.fixed,
            SupportType.FREE: cls,
        }
        if kind not in builders:
            raise ValueError(f"{kind} has no canonical restraint pattern; build it explicitly")
        support = builders[kind](node_id)
        support.angle = angle
        return support

    # -- queries -------------------------------------------------------------

    @property
    def restraints(self) -> tuple[bool, bool, bool]:
        return self.ux, self.uy, self.rz

    @property
    def restraint_count(self) -> int:
        """Number of reaction components this support provides."""
        return sum(self.restraints)

    @property
    def is_free(self) -> bool:
        return self.restraint_count == 0

    @property
    def is_inclined(self) -> bool:
        return abs(self.angle) > 1e-12

    @property
    def type(self) -> SupportType:
        """Classify into a named type, or ``CUSTOM`` if it matches none."""
        match self.restraints:
            case (False, False, False):
                return SupportType.FREE
            case (True, True, False):
                return SupportType.PIN
            case (False, True, False):
                return SupportType.ROLLER_X
            case (True, False, False):
                return SupportType.ROLLER_Y
            case (True, True, True):
                return SupportType.FIXED
            case _:
                return SupportType.CUSTOM

    @property
    def angle_deg(self) -> float:
        return math.degrees(self.angle)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "node": self.node_id,
            "ux": self.ux,
            "uy": self.uy,
            "rz": self.rz,
        }
        if self.is_inclined:
            data["angle"] = self.angle
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Support:
        return cls(
            node_id=int(data["node"]),
            ux=bool(data.get("ux", False)),
            uy=bool(data.get("uy", False)),
            rz=bool(data.get("rz", False)),
            angle=float(data.get("angle", 0.0)),
        )
