"""Member (bar / beam element)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Member:
    """A straight member running from node ``node_i`` to node ``node_j``.

    The i→j direction defines the element local x axis (conventions §4), so it also fixes the
    sign of every reported end force. Reversing a member reverses V and M signs — the GUI must
    therefore never silently reorder the ends.

    ``release_i`` / ``release_j`` are ``(ux, uy, rz)`` end releases in *local* axes. Only the
    ``rz`` slot (an internal hinge) is honoured by the frame element, and only from Phase 9;
    they are stored from the start so files written today remain forward-compatible.
    """

    id: int
    node_i: int
    node_j: int
    material_id: int
    section_id: int
    release_i: tuple[bool, bool, bool] = (False, False, False)
    release_j: tuple[bool, bool, bool] = (False, False, False)
    label: str = ""

    def __post_init__(self) -> None:
        if self.node_i == self.node_j:
            raise ValueError(f"Member {self.id}: start and end node are both {self.node_i}")

    @property
    def nodes(self) -> tuple[int, int]:
        return self.node_i, self.node_j

    @property
    def has_releases(self) -> bool:
        return any(self.release_i) or any(self.release_j)

    def connects(self, node_id: int) -> bool:
        return node_id in (self.node_i, self.node_j)

    def other_node(self, node_id: int) -> int:
        """Given one end node id, return the other. Raises if ``node_id`` is not an end."""
        if node_id == self.node_i:
            return self.node_j
        if node_id == self.node_j:
            return self.node_i
        raise ValueError(f"Node {node_id} is not an end of member {self.id}")

    def same_ends_as(self, other: Member) -> bool:
        """True when both members join the same pair of nodes, in either order."""
        return {self.node_i, self.node_j} == {other.node_i, other.node_j}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "i": self.node_i,
            "j": self.node_j,
            "material": self.material_id,
            "section": self.section_id,
        }
        if any(self.release_i):
            data["release_i"] = list(self.release_i)
        if any(self.release_j):
            data["release_j"] = list(self.release_j)
        if self.label:
            data["label"] = self.label
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Member:
        def _releases(key: str) -> tuple[bool, bool, bool]:
            raw = data.get(key, [False, False, False])
            seq = list(raw)
            return bool(seq[0]), bool(seq[1]), bool(seq[2])

        return cls(
            id=int(data["id"]),
            node_i=int(data["i"]),
            node_j=int(data["j"]),
            material_id=int(data["material"]),
            section_id=int(data["section"]),
            release_i=_releases("release_i"),
            release_j=_releases("release_j"),
            label=str(data.get("label", "")),
        )


@dataclass(slots=True)
class MemberGeometry:
    """Derived geometry of a member, computed by ``Structure.member_geometry``."""

    length: float
    cos: float
    sin: float
    angle_deg: float
    xi: float = field(default=0.0)
    yi: float = field(default=0.0)
    xj: float = field(default=0.0)
    yj: float = field(default=0.0)
