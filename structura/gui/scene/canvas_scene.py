"""The drawing canvas.

Owns the item graph, paints the grid, and turns a finished node drag into a single undo step.

Items are **reconciled** against the model rather than rebuilt from scratch: on every change
the scene diffs the ids it is showing against the ids the model has, then creates, deletes or
repositions only what differs. Rebuilding everything would be simpler still, but it destroys
selection and hover state on every edit, which is immediately noticeable when dragging.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent

from ...core.analysis import AnalysisResult
from ...core.model import Structure
from ...core.units import UnitSystem
from ..commands import MoveNodesCommand
from ..document import Document
from . import coords
from .grid import choose_spacing, grid_lines
from .items import MemberItem, NodeItem, PreviewLineItem
from .items.load_item import LoadItem
from .items.result_items import DiagramLegendItem, MemberResultItem, ReactionItem
from .items.support_item import SupportItem
from .snapping import SnapSettings

COLOUR_BACKGROUND = QColor(250, 250, 248)
COLOUR_GRID_MINOR = QColor(228, 230, 233)
COLOUR_GRID_MAJOR = QColor(206, 210, 215)
COLOUR_AXIS = QColor(168, 176, 184)

SCENE_MARGIN_METRES = 5.0
"""Empty space kept around the model so there is always somewhere to draw."""


class CanvasScene(QGraphicsScene):
    """Scene holding the structure's items."""

    snapHintChanged = Signal(str)
    """Short text for the status bar describing what the cursor is snapped to."""

    sceneDoubleClicked = Signal(int)
    """A member was double-clicked. Carries its id - the shortcut to member details."""

    viewScaleChanged = Signal(float)
    """The zoom changed. The status bar reads it; nothing else should need to."""

    def __init__(self, document: Document) -> None:
        super().__init__()
        self.document = document
        self.snap_settings = SnapSettings()
        self.grid_visible = True
        self.view_scale = 1.0
        self.tool: object | None = None

        self._node_items: dict[int, NodeItem] = {}
        self._member_items: dict[int, MemberItem] = {}
        self._support_items: dict[int, SupportItem] = {}
        self._load_items: dict[int, LoadItem] = {}
        self._drag_start: dict[int, tuple[float, float]] = {}

        self._result_items: dict[int, MemberResultItem] = {}
        self._reaction_items: dict[int, ReactionItem] = {}
        self._legend: DiagramLegendItem | None = None
        self._results_visible = True

        self.preview = PreviewLineItem()
        self.preview.hide()
        self.addItem(self.preview)

        self.setBackgroundBrush(COLOUR_BACKGROUND)
        document.modelChanged.connect(self.sync)
        self.sync()

    # ------------------------------------------------------------------ model sync

    @property
    def structure(self) -> Structure:
        return self.document.structure

    def sync(self) -> None:
        """Reconcile the item graph with the model."""
        structure = self.structure

        for node_id in [n for n in self._node_items if n not in structure.nodes]:
            item = self._node_items.pop(node_id)
            item.detach_all()
            self.removeItem(item)

        for member_id in [m for m in self._member_items if m not in structure.members]:
            self.removeItem(self._member_items.pop(member_id))

        for node_id, node in structure.nodes.items():
            item = self._node_items.get(node_id)
            target = coords.to_scene(node.x, node.y)
            if item is None:
                item = NodeItem(node_id)
                self._node_items[node_id] = item
                self.addItem(item)
                item.setPos(*target)
            elif (item.pos().x(), item.pos().y()) != target:
                item.setPos(*target)

        for member_id, member in structure.members.items():
            item = self._member_items.get(member_id)
            node_i = self._node_items.get(member.node_i)
            node_j = self._node_items.get(member.node_j)
            if node_i is None or node_j is None:
                continue
            if item is None:
                item = MemberItem(member_id, node_i, node_j)
                item.update_hit_width(self.view_scale)
                self._member_items[member_id] = item
                self.addItem(item)
            else:
                # Endpoints can change identity when a member is restored by undo.
                item.node_i, item.node_j = node_i, node_j
                node_i.attach_member(item)
                node_j.attach_member(item)
                item.update_geometry()

        self._sync_supports(structure)
        self._sync_loads(structure)
        self._sync_result_geometry()
        self._update_scene_rect()

    def _sync_supports(self, structure: Structure) -> None:
        """Reconcile support symbols. A joint has at most one."""
        for node_id in [n for n in self._support_items if n not in structure.supports]:
            self.removeItem(self._support_items.pop(node_id))

        for node_id, support in structure.supports.items():
            node = structure.nodes.get(node_id)
            if node is None:
                continue
            item = self._support_items.get(node_id)
            if item is None:
                item = SupportItem(node_id, support)
                self._support_items[node_id] = item
                self.addItem(item)
            else:
                item.update_support(support)
            item.setPos(*coords.to_scene(node.x, node.y))

    def _sync_loads(self, structure: Structure) -> None:
        """Reconcile load arrows for the active load case.

        Arrow length is relative to the largest load present, so the drawing stays readable
        whether the model is expressed in newtons or meganewtons.
        """
        case = structure.active_load_case
        by_node = {load.node_id: load for load in case.nodal if not load.is_zero}
        reference = max(
            (max(abs(load.fx), abs(load.fy)) for load in by_node.values()), default=0.0
        )

        for node_id in [n for n in self._load_items if n not in by_node]:
            self.removeItem(self._load_items.pop(node_id))

        for node_id, load in by_node.items():
            node = structure.nodes.get(node_id)
            if node is None:
                continue
            item = self._load_items.get(node_id)
            if item is None:
                item = LoadItem(node_id, load, reference)
                self._load_items[node_id] = item
                self.addItem(item)
            else:
                item.update_load(load, reference)
            item.setPos(*coords.to_scene(node.x, node.y))

    # ------------------------------------------------------------------ results

    def show_results(self, result: AnalysisResult, units: UnitSystem) -> None:
        """Draw member forces, reactions and the legend for a finished analysis."""
        self.clear_results()
        structure = self.structure
        peak = result.max_abs_axial

        for member_id, member_result in result.members.items():
            member = structure.members.get(member_id)
            if member is None:
                continue
            node_i = structure.nodes.get(member.node_i)
            node_j = structure.nodes.get(member.node_j)
            if node_i is None or node_j is None:
                continue
            item = MemberResultItem(
                member_id,
                QPointF(*coords.to_scene(node_i.x, node_i.y)),
                QPointF(*coords.to_scene(node_j.x, node_j.y)),
                member_result,
                peak,
                units,
            )
            item.update_view_scale(self.view_scale)
            item.setVisible(self._results_visible)
            self._result_items[member_id] = item
            self.addItem(item)

        peak_reaction = max((r.magnitude for r in result.reactions.values()), default=0.0)
        for node_id, reaction in result.reactions.items():
            node = structure.nodes.get(node_id)
            if node is None:
                continue
            reaction_item = ReactionItem(node_id, reaction, peak_reaction, units)
            reaction_item.setPos(*coords.to_scene(node.x, node.y))
            reaction_item.setVisible(self._results_visible)
            self._reaction_items[node_id] = reaction_item
            self.addItem(reaction_item)

        self._legend = DiagramLegendItem(peak, units)
        self._legend.setVisible(self._results_visible)
        self.addItem(self._legend)
        self.place_legend()

    def clear_results(self) -> None:
        """Remove every result overlay, leaving the drawing itself untouched."""
        for item in self._result_items.values():
            self.removeItem(item)
        for reaction_item in self._reaction_items.values():
            self.removeItem(reaction_item)
        self._result_items.clear()
        self._reaction_items.clear()
        if self._legend is not None:
            self.removeItem(self._legend)
            self._legend = None

    def set_results_visible(self, visible: bool) -> None:
        self._results_visible = visible
        for item in self._result_items.values():
            item.setVisible(visible)
        for reaction_item in self._reaction_items.values():
            reaction_item.setVisible(visible)
        if self._legend is not None:
            self._legend.setVisible(visible)

    def set_results_stale(self, stale: bool) -> None:
        """Fade the overlays once the model no longer matches the numbers on screen.

        Fading rather than deleting is deliberate: the user can still see roughly what the last
        run said while they finish editing, but nothing on screen looks authoritative.
        """
        opacity = 0.25 if stale else 1.0
        for item in self._result_items.values():
            item.setOpacity(opacity)
        for reaction_item in self._reaction_items.values():
            reaction_item.setOpacity(opacity)
        if self._legend is not None:
            self._legend.setOpacity(opacity)

    def place_legend(self) -> None:
        """Park the legend in the top-left corner of whatever is currently on screen."""
        if self._legend is None:
            return
        views = self.views()
        if not views:
            return
        corner = views[0].mapToScene(views[0].viewport().rect().topLeft())
        margin = 12.0 / max(self.view_scale, 1e-9)
        self._legend.setPos(corner.x() + margin, corner.y() + margin)

    def _sync_result_geometry(self) -> None:
        """Keep result bands attached to their members after a geometry edit."""
        structure = self.structure
        for member_id, item in list(self._result_items.items()):
            member = structure.members.get(member_id)
            if member is None:
                self.removeItem(self._result_items.pop(member_id))
                continue
            node_i = structure.nodes.get(member.node_i)
            node_j = structure.nodes.get(member.node_j)
            if node_i is not None and node_j is not None:
                item.update_endpoints(
                    QPointF(*coords.to_scene(node_i.x, node_i.y)),
                    QPointF(*coords.to_scene(node_j.x, node_j.y)),
                )

    def _update_scene_rect(self) -> None:
        """Derive the scene rect from the *model*, not from ``itemsBoundingRect``.

        Node handles ignore the view transform, so their contribution to an item-derived
        bounding rect is not meaningful. Model bounds plus a margin are both correct and
        stable while the user is drawing.
        """
        xmin, ymin, xmax, ymax = self.structure.bounds()
        margin = coords.scene_length(SCENE_MARGIN_METRES)
        left, top = coords.to_scene(xmin, ymax)
        right, bottom = coords.to_scene(xmax, ymin)
        rect = QRectF(left, top, max(right - left, 1.0), max(bottom - top, 1.0))
        self.setSceneRect(rect.adjusted(-margin, -margin, margin, margin))

    def set_view_scale(self, scale: float) -> None:
        """Told by the view whenever the zoom changes."""
        if scale <= 0.0 or scale == self.view_scale:
            return
        self.view_scale = scale
        for item in self._member_items.values():
            item.update_hit_width(scale)
        for result_item in self._result_items.values():
            result_item.update_view_scale(scale)
        self.place_legend()
        self.viewScaleChanged.emit(scale)
        self.invalidate(self.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer)

    # ------------------------------------------------------------------ lookup

    def node_item(self, node_id: int) -> NodeItem | None:
        return self._node_items.get(node_id)

    def member_item(self, member_id: int) -> MemberItem | None:
        return self._member_items.get(member_id)

    def selected_node_ids(self) -> list[int]:
        return sorted(i.node_id for i in self.selectedItems() if isinstance(i, NodeItem))

    def selected_member_ids(self) -> list[int]:
        return sorted(i.member_id for i in self.selectedItems() if isinstance(i, MemberItem))

    def select_ids(
        self, node_ids: Sequence[int] | None = None, member_ids: Sequence[int] | None = None
    ) -> None:
        """Programmatic selection, used by the model tree and diagnostics lists."""
        self.clearSelection()
        for node_id in node_ids or ():
            item = self._node_items.get(node_id)
            if item is not None:
                item.setSelected(True)
        for member_id in member_ids or ():
            item = self._member_items.get(member_id)
            if item is not None:
                item.setSelected(True)

    def model_tolerance(self) -> float:
        """The snap grab radius converted from device pixels to metres at the current zoom."""
        pixels = self.snap_settings.pixel_tolerance
        return coords.model_length(pixels / self.view_scale) if self.view_scale > 0 else 0.1

    def grid_step_metres(self) -> float:
        return choose_spacing(self.view_scale).minor_metres

    # ------------------------------------------------------------------ grid

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, COLOUR_BACKGROUND)
        if not self.grid_visible:
            return

        painter.save()
        # Grid lines are hairlines; antialiasing only blurs them and costs time.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        spacing = choose_spacing(self.view_scale)
        self._paint_grid_lines(painter, rect, spacing.minor_scene, COLOUR_GRID_MINOR, 0.0)
        self._paint_grid_lines(painter, rect, spacing.major_scene, COLOUR_GRID_MAJOR, 0.0)

        axis_pen = QPen(COLOUR_AXIS)
        axis_pen.setCosmetic(True)
        axis_pen.setWidthF(1.4)
        painter.setPen(axis_pen)
        if rect.left() <= 0.0 <= rect.right():
            painter.drawLine(QPointF(0.0, rect.top()), QPointF(0.0, rect.bottom()))
        if rect.top() <= 0.0 <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), 0.0), QPointF(rect.right(), 0.0))

        painter.restore()

    def _paint_grid_lines(
        self, painter: QPainter, rect: QRectF, step: float, colour: QColor, width: float
    ) -> None:
        pen = QPen(colour)
        pen.setCosmetic(True)
        pen.setWidthF(width)
        painter.setPen(pen)

        for x in grid_lines(rect.left(), rect.right(), step):
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for y in grid_lines(rect.top(), rect.bottom(), step):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    # ------------------------------------------------------------------ interaction

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Double-clicking a member is the fastest route to its details."""
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, MemberItem):
            self.sceneDoubleClicked.emit(item.member_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        tool = self.tool
        if tool is not None and tool.mouse_press(self, event):  # type: ignore[attr-defined]
            event.accept()
            return
        super().mousePressEvent(event)
        self._capture_drag_start()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        tool = self.tool
        if tool is not None and tool.mouse_move(self, event):  # type: ignore[attr-defined]
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        tool = self.tool
        if tool is not None and tool.mouse_release(self, event):  # type: ignore[attr-defined]
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._commit_drag()

    def _capture_drag_start(self) -> None:
        """Remember where the selected joints were before a drag begins."""
        self._drag_start = {
            item.node_id: coords.to_model(item.pos().x(), item.pos().y())
            for item in self.selectedItems()
            if isinstance(item, NodeItem)
        }

    def _commit_drag(self) -> None:
        """Turn a finished drag into exactly one undo step.

        The model was untouched while the items moved, so this is where the drag becomes real.
        A drag that ended where it started is discarded rather than pushed as an empty step.
        """
        if not self._drag_start:
            return

        moves: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {}
        for node_id, start in self._drag_start.items():
            item = self._node_items.get(node_id)
            if item is None:
                continue
            end = coords.to_model(item.pos().x(), item.pos().y())
            if end != start:
                moves[node_id] = (start, end)
        self._drag_start = {}

        if not moves:
            return

        command = MoveNodesCommand(self.document, moves)
        if not command.is_noop:
            self.document.push(command)
