"""Interaction tools.

Each tool is a small state machine fed scene mouse events. A handler returns ``True`` to say
"I consumed this", which stops the scene passing it on to Qt's own selection machinery.

The select tool consumes nothing: Qt's built-in selection, rubber-banding and item dragging
are already correct, and re-implementing them would only introduce differences from what users
expect. The scene converts the resulting drag into a single undo step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from ...core import geometry
from ...core.model import NodalLoad, Support, SupportType
from ..commands import (
    AddMemberCommand,
    AddNodeCommand,
    SetNodalLoadCommand,
    SetSupportCommand,
)
from ..scene import coords
from ..scene.snapping import SnapResult, snap_point

if TYPE_CHECKING:  # pragma: no cover
    from ..scene.canvas_scene import CanvasScene


class Tool:
    """Base class. Every handler defaults to "not handled"."""

    name = "tool"
    status_hint = ""

    def activate(self, scene: CanvasScene) -> None:
        """Called when the tool becomes current."""

    def deactivate(self, scene: CanvasScene) -> None:
        """Called when another tool takes over. Must leave no visual state behind."""
        scene.preview.hide()

    def mouse_press(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        return False

    def mouse_move(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        return False

    def mouse_release(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        return False

    def cancel(self, scene: CanvasScene) -> bool:
        """Escape pressed. Return True if there was something to abandon."""
        return False

    # -- shared helpers -------------------------------------------------

    @staticmethod
    def _snap(
        scene: CanvasScene,
        event: QGraphicsSceneMouseEvent,
        anchor: tuple[float, float] | None = None,
    ) -> SnapResult:
        """Resolve an event position to a model point, honouring the snap settings."""
        model_x, model_y = coords.point_to_model(event.scenePos())
        return snap_point(
            scene.structure,
            model_x,
            model_y,
            tolerance=scene.model_tolerance(),
            grid_step=scene.grid_step_metres(),
            settings=scene.snap_settings,
            anchor=anchor,
            constrain_angle=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
        )

    @staticmethod
    def _is_left(event: QGraphicsSceneMouseEvent) -> bool:
        return bool(event.button() == Qt.MouseButton.LeftButton)


class SelectTool(Tool):
    """Select, move and delete. Consumes nothing so Qt's own behaviour applies."""

    name = "select"
    status_hint = "Click to select. Drag to move. Shift-click to add. Del to delete."

    def mouse_move(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        scene.snapHintChanged.emit("")
        return False


class NodeTool(Tool):
    """Place joints."""

    name = "node"
    status_hint = "Click to place a joint. Shift constrains to 15 degree steps."

    def mouse_press(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        if not self._is_left(event):
            return False

        result = self._snap(scene, event)
        if result.is_existing_node:
            # Placing a joint on top of an existing one would create a silent duplicate:
            # visually identical, structurally disconnected. Select it instead.
            scene.select_ids(node_ids=[result.node_id] if result.node_id else [])
            return True

        scene.document.push(AddNodeCommand(scene.document, result.x, result.y))
        return True

    def mouse_move(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        scene.snapHintChanged.emit(self._snap(scene, event).describe())
        return False


class MemberTool(Tool):
    """Draw members, creating the joints they need.

    Click a start point, then an end point. Joints are created where none exist, and the whole
    thing lands on the undo stack as one entry - undoing a member the user just drew should
    not leave two orphan joints behind.
    """

    name = "member"
    status_hint = "Click two joints to connect. Esc cancels. Shift constrains the angle."

    def __init__(self) -> None:
        self._start: tuple[float, float] | None = None
        self._start_node_id: int | None = None

    def deactivate(self, scene: CanvasScene) -> None:
        self.cancel(scene)
        super().deactivate(scene)

    def cancel(self, scene: CanvasScene) -> bool:
        had_start = self._start is not None
        self._start = None
        self._start_node_id = None
        scene.preview.hide()
        return had_start

    def mouse_press(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        if not self._is_left(event):
            return False

        result = self._snap(scene, event, anchor=self._start)

        if self._start is None:
            self._start = (result.x, result.y)
            self._start_node_id = result.node_id if result.is_existing_node else None
            scene.preview.set_line(
                QPointF(*coords.to_scene(result.x, result.y)),
                event.scenePos(),
            )
            scene.preview.show()
            return True

        self._finish(scene, result)
        return True

    def mouse_move(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        result = self._snap(scene, event, anchor=self._start)
        scene.snapHintChanged.emit(result.describe())
        if self._start is not None:
            scene.preview.set_line(
                QPointF(*coords.to_scene(*self._start)),
                QPointF(*coords.to_scene(result.x, result.y)),
            )
        return False

    def _finish(self, scene: CanvasScene, end: SnapResult) -> None:
        """Create whatever joints are missing plus the member, as one undo entry."""
        document = scene.document
        structure = document.structure

        start = self._start
        assert start is not None
        start_id = self._start_node_id
        end_id = end.node_id if end.is_existing_node else None

        if start_id is not None and start_id == end_id:
            return  # a member from a joint to itself is not a member
        if geometry.points_coincide(start[0], start[1], end.x, end.y):
            # Two clicks on the same empty point would otherwise create a pair of coincident
            # joints joined by a zero-length member.
            return

        document.undo_stack.beginMacro("Add member")
        try:
            if start_id is None:
                command = AddNodeCommand(document, start[0], start[1])
                document.push(command)
                start_id = command.node_id
            if end_id is None:
                command = AddNodeCommand(document, end.x, end.y)
                document.push(command)
                end_id = command.node_id

            if start_id != end_id and structure.find_member(start_id, end_id) is None:
                document.push(AddMemberCommand(document, start_id, end_id))
        finally:
            document.undo_stack.endMacro()

        # Chain from the joint just reached, so a truss can be drawn without re-clicking.
        self._start = (end.x, end.y)
        self._start_node_id = end_id


class _JointTool(Tool):
    """Shared behaviour for tools that act on an existing joint.

    Neither supports nor loads may create geometry: attaching one to a joint the user did not
    mean to create would be worse than doing nothing, so a click on empty space reports why it
    was ignored instead of silently adding a node.
    """

    miss_hint = "Click directly on a joint."

    def _joint_under(
        self, scene: CanvasScene, event: QGraphicsSceneMouseEvent
    ) -> int | None:
        result = self._snap(scene, event)
        if result.is_existing_node and result.node_id is not None:
            return result.node_id
        scene.snapHintChanged.emit(self.miss_hint)
        return None


class SupportTool(_JointTool):
    """Apply supports. Clicking a joint that already has this support removes it."""

    name = "support"

    def __init__(self, support_type: SupportType = SupportType.PIN) -> None:
        self.support_type = support_type

    @property
    def status_hint(self) -> str:  # type: ignore[override]
        """Names the support currently selected, so the toolbar state is never ambiguous."""
        return (
            f"Click a joint to apply a {self.support_type.value.replace('_', ' ')} support. "
            "Click again to remove it."
        )

    def mouse_press(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        if not self._is_left(event):
            return False
        node_id = self._joint_under(scene, event)
        if node_id is None:
            return True

        existing = scene.structure.supports.get(node_id)
        if existing is not None and existing.type is self.support_type:
            support: Support | None = None  # toggle the same support off
        else:
            support = Support.from_type(node_id, self.support_type)

        scene.document.push(SetSupportCommand(scene.document, node_id, support))
        return True

    def mouse_move(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        scene.snapHintChanged.emit(self._snap(scene, event).describe())
        return False


class LoadTool(_JointTool):
    """Apply joint forces.

    The value comes from ``prompt``, a callable the main window injects so the tool itself owns
    no dialog code - that keeps it drivable from a test without a modal window appearing. When
    no prompt is supplied the tool applies ``default_load``, which is what makes it usable
    headlessly.
    """

    name = "load"
    status_hint = "Click a joint to apply or edit a force."

    def __init__(
        self,
        prompt: Callable[[NodalLoad], NodalLoad | None] | None = None,
        default_load: NodalLoad | None = None,
    ) -> None:
        self.prompt = prompt
        self.default_load = default_load or NodalLoad(0, fy=-10_000.0)

    def mouse_press(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        if not self._is_left(event):
            return False
        node_id = self._joint_under(scene, event)
        if node_id is None:
            return True

        case = scene.structure.active_load_case
        existing = next((load for load in case.nodal if load.node_id == node_id), None)
        current = existing or NodalLoad(
            node_id, self.default_load.fx, self.default_load.fy, self.default_load.mz
        )

        wanted = self.prompt(current) if self.prompt is not None else current
        if wanted is None:
            return True  # the user cancelled

        scene.document.push(
            SetNodalLoadCommand(scene.document, node_id, wanted.fx, wanted.fy, wanted.mz)
        )
        return True

    def mouse_move(self, scene: CanvasScene, event: QGraphicsSceneMouseEvent) -> bool:
        scene.snapHintChanged.emit(self._snap(scene, event).describe())
        return False


__all__ = [
    "LoadTool",
    "MemberTool",
    "NodeTool",
    "SelectTool",
    "SupportTool",
    "Tool",
]
