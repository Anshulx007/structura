"""Undoable model edits.

Every command follows one pattern for reversibility: the *first* redo performs the edit and
remembers what it produced; undo removes it and keeps a ``RemovalRecord``; any later redo
restores that record verbatim. Ids therefore survive an undo/redo cycle unchanged, which
matters because selection - and, from phase 4, analysis results - are keyed by id.

Node dragging pushes **one** command on mouse release carrying the start and end positions,
rather than one command per mouse-move merged together afterwards. That sidesteps
``mergeWith`` entirely, along with its habit of silently merging two separate drags of the
same node into a single undo step.
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from ...core.model import (
    AnalysisType,
    LoadCase,
    NodalLoad,
    RemovalRecord,
    Structure,
    Support,
)
from ..document import Document


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class ModelCommand(QUndoCommand):
    """Base class: holds the document and announces changes."""

    def __init__(self, document: Document, text: str) -> None:
        super().__init__(text)
        self.document = document

    @property
    def structure(self) -> Structure:
        return self.document.structure

    def _done(self) -> None:
        self.document.touch()


class AddNodeCommand(ModelCommand):
    """Create a joint at a model-space point."""

    def __init__(self, document: Document, x: float, y: float) -> None:
        super().__init__(document, "Add node")
        self._x = x
        self._y = y
        self._node_id: int | None = None
        self._record: RemovalRecord | None = None

    @property
    def node_id(self) -> int:
        """Id of the created node. Valid once the command has been pushed."""
        if self._node_id is None:
            raise RuntimeError("AddNodeCommand has not been executed yet")
        return self._node_id

    def redo(self) -> None:
        if self._record is None:
            self._node_id = self.structure.add_node(self._x, self._y).id
        else:
            self.structure.restore(self._record)
            self._record = None
        self._done()

    def undo(self) -> None:
        if self._node_id is not None:
            self._record = self.structure.remove(node_ids=[self._node_id])
        self._done()


class AddMemberCommand(ModelCommand):
    """Connect two existing joints."""

    def __init__(self, document: Document, node_i: int, node_j: int) -> None:
        super().__init__(document, "Add member")
        self._node_i = node_i
        self._node_j = node_j
        self._member_id: int | None = None
        self._record: RemovalRecord | None = None

    @property
    def member_id(self) -> int:
        """Id of the created member. Valid once the command has been pushed."""
        if self._member_id is None:
            raise RuntimeError("AddMemberCommand has not been executed yet")
        return self._member_id

    def redo(self) -> None:
        if self._record is None:
            self._member_id = self.structure.add_member(self._node_i, self._node_j).id
        else:
            self.structure.restore(self._record)
            self._record = None
        self._done()

    def undo(self) -> None:
        if self._member_id is not None:
            self._record = self.structure.remove(member_ids=[self._member_id])
        self._done()


class DeleteCommand(ModelCommand):
    """Delete joints and members, including everything that cascades from them."""

    def __init__(
        self,
        document: Document,
        node_ids: list[int] | None = None,
        member_ids: list[int] | None = None,
    ) -> None:
        self._node_ids = sorted(node_ids or [])
        self._member_ids = sorted(member_ids or [])
        self._record: RemovalRecord | None = None
        super().__init__(document, self._describe(document.structure))

    def _describe(self, structure: Structure) -> str:
        """Name the command by what will actually go, cascade included.

        "Delete 1 node, 2 members" tells the user what undo will bring back; a bare "Delete"
        does not.
        """
        doomed_members = set(self._member_ids)
        for node_id in self._node_ids:
            doomed_members.update(structure.members_at_node(node_id))

        parts: list[str] = []
        if self._node_ids:
            parts.append(_plural(len(self._node_ids), "node"))
        if doomed_members:
            parts.append(_plural(len(doomed_members), "member"))
        return "Delete " + ", ".join(parts) if parts else "Delete"

    def redo(self) -> None:
        self._record = self.structure.remove(
            node_ids=self._node_ids, member_ids=self._member_ids
        )
        self._done()

    def undo(self) -> None:
        if self._record is not None:
            self.structure.restore(self._record)
            self._record = None
        self._done()


class MoveNodesCommand(ModelCommand):
    """Move one or more joints.

    Pushed once, on mouse release, carrying both endpoints of the drag. The canvas moves items
    freely during the drag; only the finished result becomes an undo step.
    """

    def __init__(
        self,
        document: Document,
        moves: dict[int, tuple[tuple[float, float], tuple[float, float]]],
    ) -> None:
        label = "Move node" if len(moves) == 1 else f"Move {len(moves)} nodes"
        super().__init__(document, label)
        self._moves = moves

    @property
    def is_noop(self) -> bool:
        """A click that did not actually move anything must not become an undo step."""
        return all(start == end for start, end in self._moves.values())

    def redo(self) -> None:
        for node_id, (_start, end) in self._moves.items():
            if node_id in self.structure.nodes:
                self.structure.move_node(node_id, end[0], end[1])
        self._done()

    def undo(self) -> None:
        for node_id, (start, _end) in self._moves.items():
            if node_id in self.structure.nodes:
                self.structure.move_node(node_id, start[0], start[1])
        self._done()


class SetAnalysisTypeCommand(ModelCommand):
    """Switch the model between truss and frame analysis."""

    def __init__(self, document: Document, analysis_type: AnalysisType) -> None:
        super().__init__(document, f"Set analysis type to {analysis_type.value}")
        self._new = analysis_type
        self._old = document.structure.analysis_type

    def redo(self) -> None:
        self.structure.analysis_type = self._new
        self._done()

    def undo(self) -> None:
        self.structure.analysis_type = self._old
        self._done()


class SetMemberPropertyCommand(ModelCommand):
    """Change the material or section of one or more members."""

    EDITABLE = ("material_id", "section_id")

    def __init__(
        self, document: Document, member_ids: list[int], field: str, value: int
    ) -> None:
        if field not in self.EDITABLE:
            raise ValueError(f"Not an editable member property: {field!r}")
        super().__init__(document, "Change member " + field.replace("_id", ""))
        self._field = field
        self._value = value
        self._previous = {
            member_id: int(getattr(document.structure.members[member_id], field))
            for member_id in member_ids
            if member_id in document.structure.members
        }

    def redo(self) -> None:
        for member_id in self._previous:
            if member_id in self.structure.members:
                setattr(self.structure.members[member_id], self._field, self._value)
        self._done()

    def undo(self) -> None:
        for member_id, old in self._previous.items():
            if member_id in self.structure.members:
                setattr(self.structure.members[member_id], self._field, old)
        self._done()




class SetSupportCommand(ModelCommand):
    """Apply, change or remove the support at a joint.

    A node has at most one support, so this replaces rather than accumulates. Passing ``None``
    removes it, which is how the support tool implements click-to-toggle.
    """

    def __init__(self, document: Document, node_id: int, support: Support | None) -> None:
        previous = document.structure.supports.get(node_id)
        label = "Remove support" if support is None else f"Set {_support_name(support)} support"
        super().__init__(document, label)
        self._node_id = node_id
        self._new = support
        self._previous = previous

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._previous)

    def _apply(self, support: Support | None) -> None:
        if support is None:
            self.structure.remove_support(self._node_id)
        elif self._node_id in self.structure.nodes:
            self.structure.set_support(support)
        self._done()


def _support_name(support: Support) -> str:
    return support.type.value.replace("_", " ")


class SetNodalLoadCommand(ModelCommand):
    """Replace the load applied at one joint in the active load case.

    Replacing rather than appending keeps the model honest against the UI: the properties panel
    shows *the* load at a joint, so two stacked loads at one node would make the displayed value
    disagree with what the solver sees. A load of all zeros removes the entry entirely instead
    of leaving a no-op record behind.
    """

    def __init__(
        self, document: Document, node_id: int, fx: float = 0.0, fy: float = 0.0, mz: float = 0.0
    ) -> None:
        super().__init__(document, "Set joint load" if (fx or fy or mz) else "Remove joint load")
        self._node_id = node_id
        self._new = NodalLoad(node_id, fx, fy, mz)
        case = document.structure.active_load_case
        self._case_id = case.id
        self._previous = [load for load in case.nodal if load.node_id == node_id]

    def _case(self) -> LoadCase | None:
        return self.structure.load_cases.get(self._case_id)

    def redo(self) -> None:
        case = self._case()
        if case is not None:
            case.nodal = [load for load in case.nodal if load.node_id != self._node_id]
            if not self._new.is_zero:
                case.nodal.append(self._new)
        self._done()

    def undo(self) -> None:
        case = self._case()
        if case is not None:
            case.nodal = [load for load in case.nodal if load.node_id != self._node_id]
            case.nodal.extend(self._previous)
        self._done()


__all__ = [
    "AddMemberCommand",
    "AddNodeCommand",
    "DeleteCommand",
    "ModelCommand",
    "MoveNodesCommand",
    "SetAnalysisTypeCommand",
    "SetMemberPropertyCommand",
    "SetNodalLoadCommand",
    "SetSupportCommand",
]
