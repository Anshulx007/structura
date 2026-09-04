"""The ``Structure`` aggregate root — the single source of truth for a project.

Everything the GUI draws and everything the solver consumes lives here. The GUI never mutates
it directly: all changes go through ``QUndoCommand`` objects that call these methods, which is
what makes undo/redo trustworthy rather than a bolt-on.

Ids are allocated monotonically and **never reused**, because analysis results are keyed by
id. Deleting node 3 and adding a new node gives id 4, not 3.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

from .. import geometry
from ..units import DEFAULT as DEFAULT_UNITS
from ..units import UnitSystem
from .enums import AnalysisType
from .load import MemberDistLoad, MemberMoment, MemberPointLoad, NodalLoad
from .load_case import LoadCase, LoadCombination
from .material import Material, Section
from .member import Member, MemberGeometry
from .node import Node
from .support import Support

SCHEMA_VERSION = "1.0"

_T = TypeVar("_T")


@dataclass(slots=True)
class _IdAllocator:
    """Monotonic id source. Never hands out the same number twice."""

    next_id: int = 1

    def take(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def reserve(self, used: int) -> None:
        """Ensure future ids are greater than an id loaded from a file."""
        self.next_id = max(self.next_id, used + 1)


@dataclass
class Structure:
    """A complete 2D structural model."""

    name: str = "Untitled"
    analysis_type: AnalysisType = AnalysisType.TRUSS
    units: UnitSystem = field(default_factory=lambda: DEFAULT_UNITS)

    nodes: dict[int, Node] = field(default_factory=dict)
    members: dict[int, Member] = field(default_factory=dict)
    supports: dict[int, Support] = field(default_factory=dict)
    """Keyed by node id - a node has at most one support."""
    materials: dict[int, Material] = field(default_factory=dict)
    sections: dict[int, Section] = field(default_factory=dict)
    load_cases: dict[int, LoadCase] = field(default_factory=dict)
    combinations: dict[int, LoadCombination] = field(default_factory=dict)
    active_load_case_id: int = 1

    _node_ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)
    _member_ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)
    _material_ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)
    _section_ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)
    _case_ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)
    _combo_ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)

    def __post_init__(self) -> None:
        if not self.materials:
            self.add_material(Material(self._material_ids.take()))
        if not self.sections:
            self.add_section(Section(self._section_ids.take()))
        if not self.load_cases:
            self.add_load_case(LoadCase(self._case_ids.take(), name="LC1"))

    # ------------------------------------------------------------------ defaults

    @property
    def default_material_id(self) -> int:
        return next(iter(self.materials))

    @property
    def default_section_id(self) -> int:
        return next(iter(self.sections))

    @property
    def active_load_case(self) -> LoadCase:
        """The load case the GUI is currently editing and the solver will run."""
        if self.active_load_case_id not in self.load_cases:
            self.active_load_case_id = next(iter(self.load_cases))
        return self.load_cases[self.active_load_case_id]

    # ------------------------------------------------------------------ nodes

    def add_node(self, x: float, y: float, label: str = "") -> Node:
        """Create a node at ``(x, y)`` in metres, +Y up."""
        node = Node(self._node_ids.take(), x, y, label)
        self.nodes[node.id] = node
        return node

    def node_at(self, x: float, y: float, tol: float = geometry.NODE_MERGE_TOL) -> Node | None:
        """Find an existing node within ``tol`` — used for snap-to-joint and merge-on-draw."""
        for node in self.nodes.values():
            if geometry.points_coincide(node.x, node.y, x, y, tol):
                return node
        return None

    def move_node(self, node_id: int, x: float, y: float) -> None:
        node = self.nodes[node_id]
        node.x = x
        node.y = y

    def delete_node(self, node_id: int) -> None:
        """Delete a node and everything that references it.

        Cascades to attached members, the node's support, and its nodal loads — plus, via
        member deletion, any span loads on those members. Undo restores all of it because the
        command captures the removed objects before calling this.
        """
        for member_id in self.members_at_node(node_id):
            self.delete_member(member_id)
        self.supports.pop(node_id, None)
        for case in self.load_cases.values():
            case.remove_for_node(node_id)
        self.nodes.pop(node_id, None)

    def members_at_node(self, node_id: int) -> list[int]:
        """Ids of every member with an end at this node."""
        return [m.id for m in self.members.values() if m.connects(node_id)]

    def node_degree(self, node_id: int) -> int:
        """How many members meet at this node. Degree 0 or 1 is a truss-mode red flag."""
        return len(self.members_at_node(node_id))

    # ------------------------------------------------------------------ members

    def add_member(
        self,
        node_i: int,
        node_j: int,
        material_id: int | None = None,
        section_id: int | None = None,
        label: str = "",
    ) -> Member:
        """Connect two existing nodes. The i→j order fixes the local axes — see conventions §4."""
        if node_i not in self.nodes:
            raise KeyError(f"No node with id {node_i}")
        if node_j not in self.nodes:
            raise KeyError(f"No node with id {node_j}")
        member = Member(
            id=self._member_ids.take(),
            node_i=node_i,
            node_j=node_j,
            material_id=self.default_material_id if material_id is None else material_id,
            section_id=self.default_section_id if section_id is None else section_id,
            label=label,
        )
        self.members[member.id] = member
        return member

    def delete_member(self, member_id: int) -> None:
        """Delete a member and any loads applied along its span."""
        for case in self.load_cases.values():
            case.remove_for_member(member_id)
        self.members.pop(member_id, None)

    def find_member(self, node_a: int, node_b: int) -> Member | None:
        """Return an existing member joining these two nodes, in either order."""
        pair = {node_a, node_b}
        for member in self.members.values():
            if {member.node_i, member.node_j} == pair:
                return member
        return None

    def member_geometry(self, member_id: int) -> MemberGeometry:
        """Derived length, direction cosines and angle for a member."""
        member = self.members[member_id]
        ni = self.nodes[member.node_i]
        nj = self.nodes[member.node_j]
        length, c, s = geometry.direction_cosines(ni.x, ni.y, nj.x, nj.y)
        return MemberGeometry(
            length=length,
            cos=c,
            sin=s,
            angle_deg=geometry.angle_deg(ni.x, ni.y, nj.x, nj.y),
            xi=ni.x,
            yi=ni.y,
            xj=nj.x,
            yj=nj.y,
        )

    def member_length(self, member_id: int) -> float:
        return self.member_geometry(member_id).length

    def material_of(self, member: Member) -> Material:
        return self.materials[member.material_id]

    def section_of(self, member: Member) -> Section:
        return self.sections[member.section_id]

    def split_member(self, member_id: int, t: float) -> tuple[Node, Member, Member]:
        """Split a member at normalised position ``t`` in (0, 1), inserting a new joint.

        This is the physically correct answer to "I want a point load mid-span" in truss
        mode: an ideal truss member cannot carry the induced bending, but a real joint there
        can carry the load. Span loads on the original member are dropped, so callers should
        only offer this where that is what the user means.
        """
        if not 0.0 < t < 1.0:
            raise ValueError(f"Split position must be strictly inside the member, got t={t}")
        member = self.members[member_id]
        geo = self.member_geometry(member_id)
        new_node = self.add_node(
            geo.xi + t * (geo.xj - geo.xi),
            geo.yi + t * (geo.yj - geo.yi),
        )
        first = self.add_member(member.node_i, new_node.id, member.material_id, member.section_id)
        second = self.add_member(new_node.id, member.node_j, member.material_id, member.section_id)
        self.delete_member(member_id)
        return new_node, first, second

    # ------------------------------------------------------------------ supports

    def set_support(self, support: Support) -> Support:
        """Attach or replace the support at a node. One support per node."""
        if support.node_id not in self.nodes:
            raise KeyError(f"No node with id {support.node_id}")
        if support.is_free:
            self.supports.pop(support.node_id, None)
        else:
            self.supports[support.node_id] = support
        return support

    def remove_support(self, node_id: int) -> None:
        self.supports.pop(node_id, None)

    @property
    def total_restraints(self) -> int:
        """Number of reaction components. Fewer than 3 guarantees a mechanism in 2D."""
        return sum(s.restraint_count for s in self.supports.values())

    # ------------------------------------------------------------------ materials & sections

    def add_material(self, material: Material) -> Material:
        self.materials[material.id] = material
        self._material_ids.reserve(material.id)
        return material

    def new_material(self, name: str = "Material", **kwargs: float) -> Material:
        return self.add_material(Material(self._material_ids.take(), name, **kwargs))

    def add_section(self, section: Section) -> Section:
        self.sections[section.id] = section
        self._section_ids.reserve(section.id)
        return section

    def new_section(self, name: str = "Section", **kwargs: float) -> Section:
        return self.add_section(Section(self._section_ids.take(), name, **kwargs))

    # ------------------------------------------------------------------ loads

    def add_load_case(self, case: LoadCase) -> LoadCase:
        self.load_cases[case.id] = case
        self._case_ids.reserve(case.id)
        return case

    def new_load_case(self, name: str) -> LoadCase:
        return self.add_load_case(LoadCase(self._case_ids.take(), name))

    def add_nodal_load(
        self, node_id: int, fx: float = 0.0, fy: float = 0.0, mz: float = 0.0
    ) -> NodalLoad:
        """Add a joint load to the active load case. ``fy`` negative is downward."""
        if node_id not in self.nodes:
            raise KeyError(f"No node with id {node_id}")
        load = NodalLoad(node_id, fx, fy, mz)
        self.active_load_case.nodal.append(load)
        return load

    def add_member_point_load(
        self, member_id: int, a: float, fx: float = 0.0, fy: float = 0.0
    ) -> MemberPointLoad:
        if member_id not in self.members:
            raise KeyError(f"No member with id {member_id}")
        load = MemberPointLoad(member_id, a, fx, fy)
        self.active_load_case.member_point.append(load)
        return load

    def add_member_moment(self, member_id: int, a: float, mz: float) -> MemberMoment:
        if member_id not in self.members:
            raise KeyError(f"No member with id {member_id}")
        load = MemberMoment(member_id, a, mz)
        self.active_load_case.member_moment.append(load)
        return load

    def add_distributed_load(
        self,
        member_id: int,
        w1: float,
        w2: float | None = None,
        a: float = 0.0,
        b: float | None = None,
    ) -> MemberDistLoad:
        """Add a UDL (``w2`` omitted) or UVL to the active load case. Negative is downward."""
        if member_id not in self.members:
            raise KeyError(f"No member with id {member_id}")
        load = MemberDistLoad(member_id, w1, w1 if w2 is None else w2, a, b)
        self.active_load_case.member_dist.append(load)
        return load

    def add_combination(self, combo: LoadCombination) -> LoadCombination:
        self.combinations[combo.id] = combo
        self._combo_ids.reserve(combo.id)
        return combo

    # ------------------------------------------------------------------ queries

    @property
    def is_empty(self) -> bool:
        return not self.nodes and not self.members

    def bounds(self) -> tuple[float, float, float, float]:
        """Model extents ``(xmin, ymin, xmax, ymax)``. Returns a unit box when empty."""
        if not self.nodes:
            return 0.0, 0.0, 1.0, 1.0
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        return min(xs), min(ys), max(xs), max(ys)

    def characteristic_length(self) -> float:
        """Diagonal of the bounding box — the natural scale for tolerances and drawing."""
        xmin, ymin, xmax, ymax = self.bounds()
        return max(geometry.distance(xmin, ymin, xmax, ymax), 1.0)

    def duplicate_members(self) -> list[tuple[int, int]]:
        """Pairs of member ids that join the same two nodes."""
        seen: dict[frozenset[int], int] = {}
        duplicates: list[tuple[int, int]] = []
        for member in self.members.values():
            key = frozenset((member.node_i, member.node_j))
            if key in seen:
                duplicates.append((seen[key], member.id))
            else:
                seen[key] = member.id
        return duplicates

    def orphan_nodes(self) -> list[int]:
        """Nodes with no member attached."""
        return [nid for nid in self.nodes if self.node_degree(nid) == 0]

    def unstable_truss_nodes(self) -> list[int]:
        """Unsupported truss joints with fewer than two non-collinear members.

        A cheap pre-check that produces a friendly message. It is *not* authoritative — the
        null-space test on the assembled stiffness matrix is (conventions and plan §1.8).
        """
        flagged: list[int] = []
        for node_id in self.nodes:
            support = self.supports.get(node_id)
            if support is not None and support.restraint_count >= 2:
                continue
            attached = self.members_at_node(node_id)
            if len(attached) < 2:
                flagged.append(node_id)
                continue
            if support is None and self._all_collinear_at(node_id, attached):
                flagged.append(node_id)
        return flagged

    def _all_collinear_at(self, node_id: int, member_ids: Iterable[int]) -> bool:
        """True when every member meeting at a node shares one line."""
        origin = self.nodes[node_id]
        directions: list[tuple[float, float]] = []
        for member_id in member_ids:
            other = self.nodes[self.members[member_id].other_node(node_id)]
            try:
                _, c, s = geometry.direction_cosines(origin.x, origin.y, other.x, other.y)
            except ValueError:
                continue
            directions.append((c, s))
        if len(directions) < 2:
            return True
        c0, s0 = directions[0]
        return all(abs(c0 * s - s0 * c) < 1e-9 for c, s in directions[1:])

    # ------------------------------------------------------------------ serialisation

    def to_dict(self) -> dict[str, Any]:
        """Canonical dictionary form — also the basis of ``content_hash``."""
        return {
            "schema_version": SCHEMA_VERSION,
            "meta": {"name": self.name},
            "display_units": self.units.to_dict(),
            "analysis_type": self.analysis_type.value,
            "materials": [m.to_dict() for m in self._sorted(self.materials)],
            "sections": [s.to_dict() for s in self._sorted(self.sections)],
            "nodes": [n.to_dict() for n in self._sorted(self.nodes)],
            "members": [m.to_dict() for m in self._sorted(self.members)],
            "supports": [self.supports[k].to_dict() for k in sorted(self.supports)],
            "load_cases": [c.to_dict() for c in self._sorted(self.load_cases)],
            "combinations": [c.to_dict() for c in self._sorted(self.combinations)],
            "active_load_case": self.active_load_case_id,
        }

    @staticmethod
    def _sorted(mapping: Mapping[int, _T]) -> list[_T]:
        """Values ordered by id — so serialisation is deterministic and the hash is stable."""
        return [mapping[key] for key in sorted(mapping)]

    def content_hash(self) -> str:
        """Stable hash of everything that affects the analysis.

        ``AnalysisResult`` stores the hash it was computed from. When the two disagree, the
        displayed results are stale and the GUI must grey them out instead of showing numbers
        that no longer describe the drawing on screen.

        Deliberately excludes ``name``, display units and labels — none change the answer.
        """
        payload = self.to_dict()
        payload.pop("meta", None)
        payload.pop("display_units", None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Structure:
        """Rebuild a structure from its canonical dictionary form.

        Id allocators are advanced past every loaded id so newly created objects can never
        collide with existing ones.
        """
        meta = data.get("meta", {})
        structure = cls(
            name=str(meta.get("name", "Untitled")),
            analysis_type=AnalysisType(data.get("analysis_type", AnalysisType.TRUSS.value)),
            units=UnitSystem.from_dict(data.get("display_units", {})),
            materials={},
            sections={},
            load_cases={},
        )
        for raw in data.get("materials", []):
            structure.add_material(Material.from_dict(raw))
        for raw in data.get("sections", []):
            structure.add_section(Section.from_dict(raw))
        for raw in data.get("nodes", []):
            node = Node.from_dict(raw)
            structure.nodes[node.id] = node
            structure._node_ids.reserve(node.id)
        for raw in data.get("members", []):
            member = Member.from_dict(raw)
            structure.members[member.id] = member
            structure._member_ids.reserve(member.id)
        for raw in data.get("supports", []):
            support = Support.from_dict(raw)
            structure.supports[support.node_id] = support
        for raw in data.get("load_cases", []):
            structure.add_load_case(LoadCase.from_dict(raw))
        for raw in data.get("combinations", []):
            structure.add_combination(LoadCombination.from_dict(raw))
        structure.active_load_case_id = int(data.get("active_load_case", 1))
        structure.__post_init__()
        return structure
