"""Applied loads.

Sign convention (conventions §10): ``fy = -10_000`` is a 10 kN **downward** load; ``mz`` is
counter-clockwise positive. Nothing here is "downward by default" — stored values are signed.

Positions along a member (``a``, ``b``) are absolute distances in metres measured from node i
along the member. That matches how loads are specified in practice ("2 m from the left end").
Validation rejects positions beyond the member length, which is how a geometry edit that
invalidates a load gets caught instead of silently misplacing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import LoadDirection


@dataclass(slots=True)
class NodalLoad:
    """Concentrated force and/or moment applied directly at a joint.

    Valid in both truss and frame mode. In truss mode ``mz`` must be zero, since an ideal
    pinned joint cannot transmit a moment.
    """

    node_id: int
    fx: float = 0.0
    fy: float = 0.0
    mz: float = 0.0

    @property
    def is_zero(self) -> bool:
        return self.fx == 0.0 and self.fy == 0.0 and self.mz == 0.0

    def scaled(self, factor: float) -> NodalLoad:
        return NodalLoad(self.node_id, self.fx * factor, self.fy * factor, self.mz * factor)

    def to_dict(self) -> dict[str, Any]:
        return {"node": self.node_id, "fx": self.fx, "fy": self.fy, "mz": self.mz}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodalLoad:
        return cls(
            node_id=int(data["node"]),
            fx=float(data.get("fx", 0.0)),
            fy=float(data.get("fy", 0.0)),
            mz=float(data.get("mz", 0.0)),
        )


@dataclass(slots=True)
class MemberPointLoad:
    """Concentrated force applied at a point along a member span.

    Frame mode only. In truss mode the GUI offers to split the member at ``a``, turning this
    into a legitimate nodal load — that is the physically correct fix, since an ideal truss
    member cannot carry the bending such a load induces.
    """

    member_id: int
    a: float
    """Distance from node i along the member, metres."""
    fx: float = 0.0
    fy: float = 0.0
    direction: LoadDirection = LoadDirection.GLOBAL_Y
    """``GLOBAL_Y``/``GLOBAL_X`` treat (fx, fy) as global; ``LOCAL_*`` treat them as local."""

    @property
    def is_local(self) -> bool:
        return self.direction in (
            LoadDirection.LOCAL_AXIAL,
            LoadDirection.LOCAL_PERPENDICULAR,
        )

    @property
    def is_zero(self) -> bool:
        return self.fx == 0.0 and self.fy == 0.0

    def scaled(self, factor: float) -> MemberPointLoad:
        return MemberPointLoad(
            self.member_id, self.a, self.fx * factor, self.fy * factor, self.direction
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "point",
            "member": self.member_id,
            "a": self.a,
            "fx": self.fx,
            "fy": self.fy,
            "direction": self.direction.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemberPointLoad:
        return cls(
            member_id=int(data["member"]),
            a=float(data["a"]),
            fx=float(data.get("fx", 0.0)),
            fy=float(data.get("fy", 0.0)),
            direction=LoadDirection(data.get("direction", LoadDirection.GLOBAL_Y.value)),
        )


@dataclass(slots=True)
class MemberMoment:
    """Concentrated moment applied at a point along a member span. CCW positive.

    Frame mode only. Produces a step discontinuity in the BMD of magnitude ``mz``.
    """

    member_id: int
    a: float
    mz: float = 0.0

    @property
    def is_zero(self) -> bool:
        return self.mz == 0.0

    def scaled(self, factor: float) -> MemberMoment:
        return MemberMoment(self.member_id, self.a, self.mz * factor)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "moment", "member": self.member_id, "a": self.a, "mz": self.mz}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemberMoment:
        return cls(
            member_id=int(data["member"]),
            a=float(data["a"]),
            mz=float(data.get("mz", 0.0)),
        )


@dataclass(slots=True)
class MemberDistLoad:
    """Linearly varying distributed load over all or part of a member span.

    ``w1 == w2`` is a UDL; otherwise it is a UVL (triangular or trapezoidal). Intensities are
    in N/m and are **signed**: a downward gravity UDL of 5 kN/m is ``w1 = w2 = -5000``.

    ``direction`` is not decoration — on an inclined member the three vertical variants give
    genuinely different answers (conventions §9). A beam-only test suite cannot catch a
    mistake here, which is why the validation cases include inclined members.
    """

    member_id: int
    w1: float
    w2: float
    a: float = 0.0
    """Start of the loaded region, metres from node i."""
    b: float | None = None
    """End of the loaded region, metres from node i. ``None`` means "to node j"."""
    direction: LoadDirection = LoadDirection.GLOBAL_Y_PROJECTED

    @property
    def is_udl(self) -> bool:
        return self.w1 == self.w2

    @property
    def is_uvl(self) -> bool:
        return self.w1 != self.w2

    @property
    def is_full_span(self) -> bool:
        return self.a == 0.0 and self.b is None

    @property
    def is_zero(self) -> bool:
        return self.w1 == 0.0 and self.w2 == 0.0

    def extent(self, member_length: float) -> tuple[float, float]:
        """Resolve ``(a, b)`` against a concrete member length."""
        return self.a, member_length if self.b is None else self.b

    def scaled(self, factor: float) -> MemberDistLoad:
        return MemberDistLoad(
            self.member_id, self.w1 * factor, self.w2 * factor, self.a, self.b, self.direction
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "udl" if self.is_udl else "uvl",
            "member": self.member_id,
            "w1": self.w1,
            "w2": self.w2,
            "a": self.a,
            "b": self.b,
            "direction": self.direction.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemberDistLoad:
        raw_b = data.get("b")
        return cls(
            member_id=int(data["member"]),
            w1=float(data["w1"]),
            w2=float(data.get("w2", data["w1"])),
            a=float(data.get("a", 0.0)),
            b=None if raw_b is None else float(raw_b),
            direction=LoadDirection(
                data.get("direction", LoadDirection.GLOBAL_Y_PROJECTED.value)
            ),
        )


MemberLoad = MemberPointLoad | MemberMoment | MemberDistLoad
AnyLoad = NodalLoad | MemberPointLoad | MemberMoment | MemberDistLoad


def member_load_from_dict(data: dict[str, Any]) -> MemberLoad:
    """Dispatch on the ``type`` tag when reading a member load from a ``.stru`` file."""
    kind = str(data.get("type", "")).lower()
    if kind == "point":
        return MemberPointLoad.from_dict(data)
    if kind == "moment":
        return MemberMoment.from_dict(data)
    if kind in ("udl", "uvl", "dist", "distributed"):
        return MemberDistLoad.from_dict(data)
    raise ValueError(f"Unknown member load type {kind!r}")
