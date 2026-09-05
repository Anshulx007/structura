"""Nodal load symbols.

Like ``NodeItem`` and ``SupportItem`` this is a glyph, so it sets
``ItemIgnoresTransformations``: the item-to-viewport mapping collapses to a translation and
every number in ``boundingRect`` and ``paint`` is a **device pixel**, while ``pos()`` stays in
scene coordinates and is set by the scene from ``coords.to_scene``.

**Why arrows are scaled relatively, never absolutely.** Arrow length is a fraction of
``reference_magnitude`` - the largest load magnitude in the model - mapped onto a fixed pixel
range. Scaling by absolute newtons cannot work: the same code has to draw a 200 N handrail push
and a 1000 kN column load, and any pixels-per-newton constant that makes one visible sends the
other four screens off the canvas. A floor is applied as well, so a load that is a thousandth of
the largest is still drawn as a recognisable arrow rather than a dot.

A moment is *not* scaled this way. ``reference_magnitude`` is a force (N) and a moment is N.m;
there is no dimensionally meaningful ratio between them, so the curl is drawn at a constant
radius and its size is read from the label.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from ....core.model import NodalLoad
from ....core.units import DEFAULT as DEFAULT_UNITS
from ....core.units import UnitSystem
from .. import coords
from . import COLOUR_NODE, NODE_Z

LOAD_Z = NODE_Z - 1.0
"""Just under the joint dot, so the arrow tip never hides the node the user has to click."""

COLOUR_LOAD = QColor(186, 54, 44)
"""Loads are annotation over the structure, so they get their own ink rather than member grey."""

COLOUR_LOAD_LABEL = COLOUR_NODE
"""Label text shares the node ink: red-on-white numerals at 8pt are hard to read."""

LOAD_MAX_LENGTH_PX = 55.0
"""Device-pixel length given to the largest load in the model."""

LOAD_MIN_LENGTH_PX = 18.0
"""Floor, so a load far smaller than the largest is still visible and identifiable."""

ARROW_PEN_PX = 1.8

ARROW_HEAD_LENGTH_PX = 9.0

ARROW_HEAD_HALF_WIDTH_PX = 4.0

MOMENT_RADIUS_PX = 15.0
"""Constant radius for the moment curl - see the module docstring for why it is not scaled."""

MOMENT_START_DEG = 45.0
"""Arc start, in Qt's arc convention: 0 is 3 o'clock and positive angles run visually CCW."""

MOMENT_SWEEP_DEG = 270.0
"""Leaves a 90-degree gap, which is what makes the curl read as a rotation rather than a ring."""

LABEL_GAP_PX = 4.0

LABEL_POINT_SIZE = 8.0


def _format_quantity(value: float, unit: str) -> str:
    """Format one display-unit number. Magnitude only - direction is shown by the arrow.

    Falls back to three decimals below 0.1 so a genuinely small load does not print as "0.0"
    and read as an input error.
    """
    magnitude = abs(value)
    decimals = 3 if 0.0 < magnitude < 0.1 else 1
    return f"{magnitude:.{decimals}f} {unit}"


def format_load_label(load: NodalLoad, units: UnitSystem) -> str:
    """Pure-ASCII caption for a nodal load, e.g. ``"10.0 kN"`` or ``"10.0 kN, 5.0 kN.m"``.

    The force part is the *resultant* of fx and fy, because that is the arrow being annotated.
    Returns an empty string for a zero load, which the caller can treat as "draw nothing".
    """
    parts: list[str] = []
    force = math.hypot(load.fx, load.fy)
    if force != 0.0:
        parts.append(_format_quantity(units.force_from_si(force), units.force))
    if load.mz != 0.0:
        parts.append(_format_quantity(units.moment_from_si(load.mz), units.moment_unit))
    return ", ".join(parts)


def _arrow_length(magnitude: float, reference_magnitude: float) -> float:
    """Map a force magnitude onto the device-pixel arrow range. See the module docstring."""
    if magnitude <= 0.0:
        return 0.0
    if reference_magnitude <= 0.0:
        return LOAD_MAX_LENGTH_PX
    ratio = min(magnitude / reference_magnitude, 1.0)
    return max(LOAD_MIN_LENGTH_PX, LOAD_MAX_LENGTH_PX * ratio)


def _add_arrow_head(path: QPainterPath, tip: QPointF, direction: QPointF, length: float) -> None:
    """Append a filled arrowhead whose point is at ``tip``, pointing along ``direction``."""
    normal = QPointF(-direction.y(), direction.x())
    base = tip - direction * length
    path.moveTo(tip)
    path.lineTo(base + normal * ARROW_HEAD_HALF_WIDTH_PX)
    path.lineTo(base - normal * ARROW_HEAD_HALF_WIDTH_PX)
    path.closeSubpath()


class LoadItem(QGraphicsItem):
    """Arrow and/or moment curl for a ``NodalLoad``, drawn at a constant device size.

    Inert like ``SupportItem``: the user selects the joint, not its annotation.

    ``units`` is optional so the required constructor signature stays
    ``LoadItem(node_id, load, reference_magnitude)``; the scene can switch display units later
    with :meth:`set_units` without rebuilding the item.
    """

    def __init__(
        self,
        node_id: int,
        load: NodalLoad,
        reference_magnitude: float,
        units: UnitSystem | None = None,
    ) -> None:
        super().__init__()
        self.node_id = node_id
        self._load = load
        self._reference = reference_magnitude
        self._units = units if units is not None else DEFAULT_UNITS
        self._fill = QPainterPath()
        self._stroke = QPainterPath()
        self._label = ""
        self._label_rect = QRectF()
        self._bounds = QRectF()
        self._font = QFont()
        self._font.setPointSizeF(LABEL_POINT_SIZE)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(LOAD_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._rebuild()

    # -- model ----------------------------------------------------------

    @property
    def load(self) -> NodalLoad:
        return self._load

    def update_load(self, load: NodalLoad, reference_magnitude: float) -> None:
        """Swap in a new load in place.

        ``reference_magnitude`` is passed again because editing *any* load can change which
        load is the largest, which resizes every other arrow in the model.

        ``prepareGeometryChange`` must precede the new paths: Qt caches the old bounding rect,
        and a longer arrow would otherwise paint outside the rect the scene index still holds.
        """
        self.prepareGeometryChange()
        self._load = load
        self._reference = reference_magnitude
        self._rebuild()
        self.update()

    def set_units(self, units: UnitSystem) -> None:
        """Change the display units of the label. Geometry is unaffected; the text width is not."""
        self.prepareGeometryChange()
        self._units = units
        self._rebuild()
        self.update()

    # -- geometry -------------------------------------------------------

    def _force_direction(self) -> QPointF | None:
        """Unit vector, in device pixels, pointing the way the force acts. ``None`` if no force.

        The model->screen y flip is delegated to ``coords.to_scene``. That mapping is a pure
        scale-and-flip with no translation, so it is valid on a *vector*, and the scale factor
        divides out when the result is normalised. Doing the flip by hand here is exactly the
        bug ``coords`` exists to prevent.
        """
        screen_x, screen_y = coords.to_scene(self._load.fx, self._load.fy)
        norm = math.hypot(screen_x, screen_y)
        if norm == 0.0:
            return None
        return QPointF(screen_x / norm, screen_y / norm)

    def _rebuild(self) -> None:
        """Rebuild paths, label and cached bounds for the current load."""
        fill = QPainterPath()
        stroke = QPainterPath()
        self._label = format_load_label(self._load, self._units)
        label_rect = QRectF()

        direction = self._force_direction()
        if direction is not None:
            magnitude = math.hypot(self._load.fx, self._load.fy)
            length = _arrow_length(magnitude, self._reference)
            # TIP is the local origin, i.e. the joint itself: on a structural drawing the
            # arrowhead sits on the point of application. TAIL is the far end, back along
            # -direction. So fy = -10 kN gives a screen direction of "down", a tail *above*
            # the joint, and an arrow pointing down into it. Swapping these two ends is the
            # classic way to draw every load in a model backwards.
            tip = QPointF(0.0, 0.0)
            tail = tip - direction * length
            head_length = min(ARROW_HEAD_LENGTH_PX, length * 0.5)
            stroke.moveTo(tail)
            stroke.lineTo(tip - direction * (head_length * 0.6))
            _add_arrow_head(fill, tip, direction, head_length)
            if self._label:
                label_rect = self._label_beyond_tail(tail, direction)
        elif self._label:
            label_rect = self._label_beside_curl()

        if self._load.mz != 0.0:
            self._add_moment_curl(fill, stroke)

        self._fill = fill
        self._stroke = stroke
        self._label_rect = label_rect

        bounds = QRectF()
        for path in (fill, stroke):
            if not path.isEmpty():
                bounds = bounds.united(path.boundingRect())
        if not label_rect.isNull():
            bounds = bounds.united(label_rect)
        margin = ARROW_PEN_PX + 1.0
        self._bounds = bounds.adjusted(-margin, -margin, margin, margin)

    def _label_size(self) -> tuple[float, float]:
        rect = QFontMetricsF(self._font).boundingRect(self._label)
        return rect.width() + 2.0, rect.height() + 1.0

    def _label_beyond_tail(self, tail: QPointF, direction: QPointF) -> QRectF:
        """Place the caption just past the arrow tail, on the far side from the joint.

        The offset includes half the label's own extent projected onto the arrow direction, so
        the text clears the shaft whatever angle the load acts at.
        """
        width, height = self._label_size()
        back = QPointF(-direction.x(), -direction.y())
        offset = LABEL_GAP_PX + 0.5 * (abs(back.x()) * width + abs(back.y()) * height)
        centre = tail + back * offset
        return QRectF(centre.x() - width / 2.0, centre.y() - height / 2.0, width, height)

    def _label_beside_curl(self) -> QRectF:
        """Place the caption to the right of a moment-only symbol, clear of the arc."""
        width, height = self._label_size()
        left = MOMENT_RADIUS_PX + LABEL_GAP_PX
        return QRectF(left, -height / 2.0, width, height)

    def _add_moment_curl(self, fill: QPainterPath, stroke: QPainterPath) -> None:
        """Append the curved arrow for ``mz``.

        Qt's arc angles are already y-up (it negates the sine internally), so a positive sweep
        draws a visually counter-clockwise arc - which is exactly the sign convention for mz
        (conventions 10). No extra inversion is needed here, unlike a painter rotation.
        """
        rect = QRectF(
            -MOMENT_RADIUS_PX, -MOMENT_RADIUS_PX, 2 * MOMENT_RADIUS_PX, 2 * MOMENT_RADIUS_PX
        )
        counter_clockwise = self._load.mz > 0.0
        sweep = MOMENT_SWEEP_DEG if counter_clockwise else -MOMENT_SWEEP_DEG
        stroke.arcMoveTo(rect, MOMENT_START_DEG)
        stroke.arcTo(rect, MOMENT_START_DEG, sweep)

        end = math.radians(MOMENT_START_DEG + sweep)
        # Arc point in device pixels; the sine is negated because Qt's arc angles run y-up.
        point = QPointF(
            MOMENT_RADIUS_PX * math.cos(end), -MOMENT_RADIUS_PX * math.sin(end)
        )
        # Tangent in the direction of travel: d/dt of that point for increasing t, flipped
        # when the sweep runs backwards. The head goes on the leading end, which is what tells
        # the reader whether the moment is CW or CCW.
        if counter_clockwise:
            tangent = QPointF(-math.sin(end), -math.cos(end))
        else:
            tangent = QPointF(math.sin(end), math.cos(end))
        _add_arrow_head(fill, point, tangent, ARROW_HEAD_LENGTH_PX)

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
        pen = QPen(COLOUR_LOAD)
        pen.setWidthF(ARROW_PEN_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        if not self._stroke.isEmpty():
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(Qt.GlobalColor.transparent)))
            painter.drawPath(self._stroke)

        if not self._fill.isEmpty():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(COLOUR_LOAD))
            painter.drawPath(self._fill)

        if self._label and not self._label_rect.isNull():
            painter.setPen(QPen(COLOUR_LOAD_LABEL))
            painter.setFont(self._font)
            painter.drawText(self._label_rect, Qt.AlignmentFlag.AlignCenter, self._label)


__all__ = [
    "ARROW_HEAD_HALF_WIDTH_PX",
    "ARROW_HEAD_LENGTH_PX",
    "ARROW_PEN_PX",
    "COLOUR_LOAD",
    "COLOUR_LOAD_LABEL",
    "LABEL_GAP_PX",
    "LABEL_POINT_SIZE",
    "LOAD_MAX_LENGTH_PX",
    "LOAD_MIN_LENGTH_PX",
    "LOAD_Z",
    "MOMENT_RADIUS_PX",
    "MOMENT_START_DEG",
    "MOMENT_SWEEP_DEG",
    "LoadItem",
    "format_load_label",
]
