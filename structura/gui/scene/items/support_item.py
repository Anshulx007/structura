"""Support symbols.

Like ``NodeItem``, a support symbol is a *glyph*, not geometry: a pin drawn at 0.01x zoom must
still be a recognisable pin. So this item sets ``ItemIgnoresTransformations``, which reduces the
item-to-viewport mapping to a pure translation. Every number in ``boundingRect`` and ``paint``
is therefore a **device pixel**, while ``pos()`` stays in scene coordinates and is set by the
scene from ``coords.to_scene``. No y coordinate is flipped here.

The symbol is built once into two ``QPainterPath`` objects - one filled, one stroked - and the
support angle is baked into them by mapping both through a ``QTransform``. Rotating the painter
instead would work for drawing but would leave ``boundingRect`` describing the *unrotated*
symbol, and Qt would then clip an inclined roller.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from ....core.model import Support, SupportType
from . import COLOUR_MEMBER, MEMBER_Z, NODE_Z

SUPPORT_Z = (MEMBER_Z + NODE_Z) / 2.0
"""Above members so the symbol is never buried, below nodes so the joint dot stays on top."""

COLOUR_SUPPORT = QColor(COLOUR_MEMBER)
"""Supports are structure, not annotation, so they share the member ink.

Copied rather than aliased: ``QColor`` is mutable, and a shared instance would let a future
theme tweak here silently repaint every member.
"""

COLOUR_SUPPORT_FILL = COLOUR_MEMBER.lighter(155)
"""Fill for the triangle body - lighter than the outline so the two edges stay readable."""

SUPPORT_PEN_PX = 1.4
"""Outline width in device pixels."""

PIN_HEIGHT_PX = 16.0
"""Apex-to-base height of the pin triangle, in device pixels."""

PIN_HALF_BASE_PX = 9.0

ROLLER_HEIGHT_PX = 12.0
"""Roller triangles are shorter than a pin's so the wheels fit in the same overall height."""

ROLLER_HALF_BASE_PX = 8.0

ROLLER_RADIUS_PX = 2.6

GROUND_HALF_WIDTH_PX = 13.0
"""Half-length of the ground line under a pin or roller."""

FIXED_HALF_WIDTH_PX = 17.0
"""The encastre wall is drawn wider than a pin's ground line.

A fixed support is only a bar plus hatching, so it has no triangle to give it presence; the
extra width is what stops it reading as a pin whose triangle failed to draw.
"""

CUSTOM_SIZE_PX = 12.0

HATCH_TICK_PX = 4.5
"""Length of one 45-degree hatch tick below a ground line."""

HATCH_STEP_PX = 5.0
"""Spacing between hatch ticks."""


def _add_ground(path: QPainterPath, base_y: float, half_width: float) -> None:
    """Append a ground line at ``base_y`` plus 45-degree hatching beneath it.

    Ticks lean down-left, which is the usual drafting convention for "this face is fixed".
    """
    path.moveTo(-half_width, base_y)
    path.lineTo(half_width, base_y)
    x = -half_width + HATCH_TICK_PX
    while x <= half_width + 1e-9:
        path.moveTo(x, base_y)
        path.lineTo(x - HATCH_TICK_PX, base_y + HATCH_TICK_PX)
        x += HATCH_STEP_PX


def _add_triangle(path: QPainterPath, height: float, half_base: float) -> None:
    """Append a triangle with its apex on the joint (the local origin) and its base below it.

    Positive local y is downward on screen because this item paints in device pixels. That is
    a drawing direction, not a model-space sign flip.
    """
    path.moveTo(0.0, 0.0)
    path.lineTo(-half_base, height)
    path.lineTo(half_base, height)
    path.closeSubpath()


class SupportItem(QGraphicsItem):
    """The conventional civil-engineering symbol for a node's boundary condition.

    Deliberately inert: the user selects the *joint*, so this item accepts no mouse buttons and
    is not selectable. Leaving it clickable would mean a click just below a joint selected the
    support glyph instead of the node the user was aiming at.
    """

    def __init__(self, node_id: int, support: Support) -> None:
        super().__init__()
        self.node_id = node_id
        self._support = support
        self._fill = QPainterPath()
        self._stroke = QPainterPath()
        self._bounds = QRectF()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(SUPPORT_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._rebuild()

    # -- model ----------------------------------------------------------

    @property
    def support(self) -> Support:
        return self._support

    def update_support(self, support: Support) -> None:
        """Swap in a new restraint pattern in place, keeping selection and Z ordering.

        ``prepareGeometryChange`` must come before the new paths are stored: Qt caches the old
        bounding rect in the scene index, and a larger new symbol would otherwise paint outside
        the rect Qt still believes in, leaving trails when the view scrolls.
        """
        self.prepareGeometryChange()
        self._support = support
        self._rebuild()
        self.update()

    # -- geometry -------------------------------------------------------

    def _rebuild(self) -> None:
        """Rebuild the fill/stroke paths and the cached bounds for the current support."""
        fill = QPainterPath()
        stroke = QPainterPath()
        kind = self._support.type
        base_rotation_deg = 0.0

        if kind is SupportType.PIN:
            _add_triangle(fill, PIN_HEIGHT_PX, PIN_HALF_BASE_PX)
            _add_ground(stroke, PIN_HEIGHT_PX, GROUND_HALF_WIDTH_PX)
        elif kind in (SupportType.ROLLER_X, SupportType.ROLLER_Y):
            _add_triangle(fill, ROLLER_HEIGHT_PX, ROLLER_HALF_BASE_PX)
            wheel_y = ROLLER_HEIGHT_PX + ROLLER_RADIUS_PX
            for wheel_x in (-ROLLER_HALF_BASE_PX / 2.0, ROLLER_HALF_BASE_PX / 2.0):
                stroke.addEllipse(
                    QPointF(wheel_x, wheel_y), ROLLER_RADIUS_PX, ROLLER_RADIUS_PX
                )
            _add_ground(stroke, wheel_y + ROLLER_RADIUS_PX, GROUND_HALF_WIDTH_PX)
            # ROLLER_Y restrains ux, so its rolling surface is vertical. Qt's positive rotation
            # is visually clockwise in this y-down frame, and clockwise 90 maps "down" to
            # "left" - which stands the wall to the left of the joint.
            if kind is SupportType.ROLLER_Y:
                base_rotation_deg = 90.0
        elif kind is SupportType.FIXED:
            # The joint sits *on* the wall face: that is what an encastre means, so the bar
            # runs through the local origin rather than being offset below it.
            _add_ground(stroke, 0.0, FIXED_HALF_WIDTH_PX)
        elif kind is SupportType.CUSTOM:
            # An unnamed restraint combination. Drawn as a plain square outline on purpose: it
            # must not be mistaken for a pin, because the reactions it produces are different.
            stroke.addRect(
                QRectF(-CUSTOM_SIZE_PX / 2.0, 0.0, CUSTOM_SIZE_PX, CUSTOM_SIZE_PX)
            )
        # SupportType.FREE falls through with empty paths - nothing to draw.

        if base_rotation_deg != 0.0:
            base = QTransform()
            base.rotate(base_rotation_deg)
            fill = base.map(fill)
            stroke = base.map(stroke)

        if self._support.is_inclined:
            # ``angle`` is CCW-positive in model space (conventions 2). Model CCW reads as
            # visually CCW on screen, but Qt's positive rotation is visually clockwise in a
            # y-down frame, so the sign is inverted here. This is an angle, not a coordinate.
            user = QTransform()
            user.rotate(-math.degrees(self._support.angle))
            fill = user.map(fill)
            stroke = user.map(stroke)

        self._fill = fill
        self._stroke = stroke

        bounds = QRectF()
        for path in (fill, stroke):
            if not path.isEmpty():
                bounds = bounds.united(path.boundingRect())
        margin = SUPPORT_PEN_PX + 1.0
        self._bounds = bounds.adjusted(-margin, -margin, margin, margin)

    def boundingRect(self) -> QRectF:
        """In device pixels, because this item ignores the view transform."""
        return self._bounds

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(COLOUR_SUPPORT)
        pen.setWidthF(SUPPORT_PEN_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        if not self._fill.isEmpty():
            painter.setPen(pen)
            painter.setBrush(QBrush(COLOUR_SUPPORT_FILL))
            painter.drawPath(self._fill)

        if not self._stroke.isEmpty():
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._stroke)


__all__ = [
    "COLOUR_SUPPORT",
    "COLOUR_SUPPORT_FILL",
    "CUSTOM_SIZE_PX",
    "FIXED_HALF_WIDTH_PX",
    "GROUND_HALF_WIDTH_PX",
    "HATCH_STEP_PX",
    "HATCH_TICK_PX",
    "PIN_HALF_BASE_PX",
    "PIN_HEIGHT_PX",
    "ROLLER_HALF_BASE_PX",
    "ROLLER_HEIGHT_PX",
    "ROLLER_RADIUS_PX",
    "SUPPORT_PEN_PX",
    "SUPPORT_Z",
    "SupportItem",
]
