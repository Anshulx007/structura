"""Canvas items.

Two sizing problems have to be solved differently, which is why the items are not symmetric:

**Node handles** must stay a constant size on screen so they remain grabbable at every zoom.
They use ``ItemIgnoresTransformations``, which makes Qt paint them in device pixels. Verified
behaviour: rubber-band queries still find them at 0.01x and 100x, and they do not inflate
``itemsBoundingRect``.

**Members** are real geometry - their length and angle are the drawing - so they live in scene
coordinates with a cosmetic pen. Their *hit* area, though, must stay a constant pixel width or
a thin line becomes unclickable when zoomed out. That width is recomputed from the scene's
current view scale, so ``CanvasScene`` must call ``update_hit_width`` on every zoom change.
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

NODE_RADIUS_PX = 4.5
"""Node handle radius in device pixels."""

NODE_SELECT_RADIUS_PX = 6.5
"""Grab radius in device pixels - larger than the drawn dot, so clicking is forgiving."""

MEMBER_HIT_PX = 7.0
"""Half-width of a member's clickable band, in device pixels."""

NODE_Z = 20.0
MEMBER_Z = 10.0

COLOUR_NODE = QColor(38, 50, 66)
COLOUR_NODE_SELECTED = QColor(226, 116, 24)
COLOUR_MEMBER = QColor(58, 78, 100)
COLOUR_MEMBER_SELECTED = QColor(226, 116, 24)


class NodeItem(QGraphicsItem):
    """A joint. Painted at a constant device size; positioned in scene coordinates."""

    def __init__(self, node_id: int) -> None:
        super().__init__()
        self.node_id = node_id
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(NODE_Z)
        self.setAcceptHoverEvents(True)
        self._members: list[MemberItem] = []
        self._hovered = False

    # -- wiring ---------------------------------------------------------

    def attach_member(self, member: MemberItem) -> None:
        """Remember a member that ends here, so a drag can drag it along."""
        if member not in self._members:
            self._members.append(member)

    def detach_all(self) -> None:
        self._members.clear()

    # -- geometry -------------------------------------------------------

    def boundingRect(self) -> QRectF:
        """In device pixels, because this item ignores the view transform."""
        r = NODE_SELECT_RADIUS_PX + 1.0
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        r = NODE_SELECT_RADIUS_PX
        path.addEllipse(QPointF(0.0, 0.0), r, r)
        return path

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = bool(self.isSelected())
        colour = COLOUR_NODE_SELECTED if selected else COLOUR_NODE
        radius = NODE_RADIUS_PX + (1.0 if (selected or self._hovered) else 0.0)

        painter.setPen(QPen(QColor(255, 255, 255), 1.2))
        painter.setBrush(QBrush(colour))
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)

    # -- interaction ----------------------------------------------------

    def hoverEnterEvent(self, event: object) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event: object) -> None:
        self._hovered = False
        self.update()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:
        """Keep attached members glued to this joint while it is dragged.

        The model is not touched here. A drag only moves items; the single
        ``MoveNodesCommand`` is pushed on mouse release, so one drag is one undo step.
        """
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for member in self._members:
                member.update_geometry()
        return super().itemChange(change, value)


class MemberItem(QGraphicsItem):
    """A member drawn between two ``NodeItem`` handles.

    Reads its endpoints from the *items*, not the model, so it follows a live drag.
    """

    def __init__(self, member_id: int, node_i: NodeItem, node_j: NodeItem) -> None:
        super().__init__()
        self.member_id = member_id
        self.node_i = node_i
        self.node_j = node_j
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(MEMBER_Z)
        self._hit_width = MEMBER_HIT_PX
        self._line = QLineF()
        node_i.attach_member(self)
        node_j.attach_member(self)
        self.update_geometry()

    # -- geometry -------------------------------------------------------

    def update_geometry(self) -> None:
        """Recompute the line from the current node positions."""
        self.prepareGeometryChange()
        self._line = QLineF(self.node_i.pos(), self.node_j.pos())

    def update_hit_width(self, view_scale: float) -> None:
        """Resize the clickable band so it stays a constant width on screen.

        ``prepareGeometryChange`` is essential: without it Qt keeps the old bounding rect and
        the widened hit area either goes unnoticed or paints outside its declared bounds.
        """
        width = MEMBER_HIT_PX / view_scale if view_scale > 0.0 else MEMBER_HIT_PX
        if width != self._hit_width:
            self.prepareGeometryChange()
            self._hit_width = width

    def boundingRect(self) -> QRectF:
        margin = self._hit_width + 1.0
        return QRectF(self._line.p1(), self._line.p2()).normalized().adjusted(
            -margin, -margin, margin, margin
        )

    def shape(self) -> QPainterPath:
        path = QPainterPath(self._line.p1())
        path.lineTo(self._line.p2())
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self._hit_width * 2.0, 1e-9))
        return stroker.createStroke(path)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = bool(self.isSelected())
        pen = QPen(COLOUR_MEMBER_SELECTED if selected else COLOUR_MEMBER)
        pen.setCosmetic(True)  # constant device width at every zoom
        pen.setWidthF(3.0 if selected else 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(self._line)


class PreviewLineItem(QGraphicsItem):
    """The rubber-band line shown while drawing a member. Never selectable, never hit-tested."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(NODE_Z + 5.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._line = QLineF()

    def set_line(self, start: QPointF, end: QPointF) -> None:
        self.prepareGeometryChange()
        self._line = QLineF(start, end)
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(self._line.p1(), self._line.p2()).normalized().adjusted(-4, -4, 4, 4)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        pen = QPen(COLOUR_MEMBER_SELECTED)
        pen.setCosmetic(True)
        pen.setWidthF(1.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(self._line)


__all__ = [
    "MEMBER_HIT_PX",
    "NODE_RADIUS_PX",
    "NODE_SELECT_RADIUS_PX",
    "MemberItem",
    "NodeItem",
    "PreviewLineItem",
]
