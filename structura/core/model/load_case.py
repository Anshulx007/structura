"""Load cases and combinations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .load import (
    AnyLoad,
    MemberDistLoad,
    MemberMoment,
    MemberPointLoad,
    NodalLoad,
    member_load_from_dict,
)


@dataclass(slots=True)
class LoadCase:
    """A named set of loads applied together.

    Loads are held in separate lists by kind rather than one polymorphic list: it keeps
    validation and assembly straightforward, and it serialises to obvious JSON.
    """

    id: int
    name: str = "LC1"
    nodal: list[NodalLoad] = field(default_factory=list)
    member_point: list[MemberPointLoad] = field(default_factory=list)
    member_moment: list[MemberMoment] = field(default_factory=list)
    member_dist: list[MemberDistLoad] = field(default_factory=list)

    def all_loads(self) -> list[AnyLoad]:
        """Every load in this case, in a stable order."""
        loads: list[AnyLoad] = []
        loads.extend(self.nodal)
        loads.extend(self.member_point)
        loads.extend(self.member_moment)
        loads.extend(self.member_dist)
        return loads

    def member_loads(self) -> list[MemberPointLoad | MemberMoment | MemberDistLoad]:
        """Only the loads applied along member spans (illegal in truss mode)."""
        loads: list[MemberPointLoad | MemberMoment | MemberDistLoad] = []
        loads.extend(self.member_point)
        loads.extend(self.member_moment)
        loads.extend(self.member_dist)
        return loads

    def loads_on_member(
        self, member_id: int
    ) -> list[MemberPointLoad | MemberMoment | MemberDistLoad]:
        return [ld for ld in self.member_loads() if ld.member_id == member_id]

    @property
    def is_empty(self) -> bool:
        return all(ld.is_zero for ld in self.all_loads())

    def add(self, load: AnyLoad) -> AnyLoad:
        """Append a load to the correct list based on its type."""
        match load:
            case NodalLoad():
                self.nodal.append(load)
            case MemberPointLoad():
                self.member_point.append(load)
            case MemberMoment():
                self.member_moment.append(load)
            case MemberDistLoad():
                self.member_dist.append(load)
        return load

    def remove_for_node(self, node_id: int) -> None:
        """Drop nodal loads attached to a node that is being deleted."""
        self.nodal = [ld for ld in self.nodal if ld.node_id != node_id]

    def remove_for_member(self, member_id: int) -> None:
        """Drop span loads attached to a member that is being deleted."""
        self.member_point = [ld for ld in self.member_point if ld.member_id != member_id]
        self.member_moment = [ld for ld in self.member_moment if ld.member_id != member_id]
        self.member_dist = [ld for ld in self.member_dist if ld.member_id != member_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "nodal": [ld.to_dict() for ld in self.nodal],
            "member": [ld.to_dict() for ld in self.member_loads()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoadCase:
        case = cls(
            id=int(data["id"]),
            name=str(data.get("name", "LC1")),
        )
        for raw in data.get("nodal", []):
            case.nodal.append(NodalLoad.from_dict(raw))
        for raw in data.get("member", []):
            case.add(member_load_from_dict(raw))
        return case


@dataclass(slots=True)
class LoadCombination:
    """A weighted sum of load cases, e.g. ``1.5 DL + 1.5 LL``.

    Linear analysis means superposition holds exactly, so a combination is evaluated by
    scaling and summing the individual case results rather than re-solving.
    """

    id: int
    name: str = "Comb1"
    factors: dict[int, float] = field(default_factory=dict)
    """Map of load-case id to its multiplier."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "factors": {str(k): v for k, v in self.factors.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoadCombination:
        raw = data.get("factors", {})
        return cls(
            id=int(data["id"]),
            name=str(data.get("name", "Comb1")),
            factors={int(k): float(v) for k, v in raw.items()},
        )
