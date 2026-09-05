"""Analysis-result overlays for the canvas.

These items are the read-only picture of a solved model: a colour-coded force band under each
member, reaction arrows at the supports, and a legend tying the colours back to numbers. They
hold no model state and never mutate one. Every number they show was computed in
``structura.core.analysis`` and converted for display exactly once, here at the boundary
(conventions section 1) - the overlays do no force arithmetic of their own.

Three sizing rules are in play, and they are deliberately not the same rule:

* the **band** is real geometry - it has to lie exactly on the member - so it lives in scene
  coordinates and is stroked with a cosmetic pen, which keeps its width constant in device
  pixels at any zoom;
* the **label**, the **reaction arrows** and the **legend** are annotation, not geometry. A
  label that grows with zoom is unreadable at both extremes, so they set
  ``ItemIgnoresTransformations``: their painting units become device pixels while ``pos()``
  stays anchored in scene coordinates. Verified at 0.01x and 100x.

Everything here is decorative. No item accepts mouse buttons and every ``shape()`` is empty, so
a click always falls through to the underlying ``MemberItem`` or ``NodeItem`` - the user selects
the member, never its annotation.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from ....core.model import MemberState

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from ....core.analysis.results import MemberResult, ReactionResult
    from ....core.units import UnitSystem

# -- stacking -------------------------------------------------------------------------------
# Sits below MEMBER_Z (10.0) so the band reads as a highlight *under* the member line rather
# than as a replacement for it; reactions sit above NODE_Z (20.0) because an arrow tip that
# disappears behind the joint dot loses the very information it carries.

RESULT_BAND_Z = 5.0
REACTION_Z = 24.0
LEGEND_Z = 60.0

# -- colour ramp ----------------------------------------------------------------------------

HUE_COMPRESSION_DEG = 0.0
"""Red family."""

HUE_TENSION_DEG = 214.0
"""Blue family."""

SATURATION_MIN = 0.35
SATURATION_MAX = 1.0

LIGHTNESS_COMPRESSION = (0.46, 0.34)
"""HSL lightness at zero and at full magnitude. Compression owns the *dark* band."""

LIGHTNESS_TENSION = (0.72, 0.58)
"""HSL lightness at zero and at full magnitude. Tension owns the *light* band."""

ZERO_FORCE_RATIO = 1.0e-6
"""Below this fraction of the peak force a member is drawn as zero-force."""

COLOUR_ZERO_FORCE = QColor(150, 155, 160)
COLOUR_LABEL_TEXT = QColor(28, 36, 46)
COLOUR_LABEL_BACKGROUND = QColor(255, 255, 255, 225)
COLOUR_REACTION = QColor(22, 128, 74)
"""Green: applied loads are drawn in the model palette (dark blue / orange), so a distinct hue
keeps "what I put in" visually separate from "what the analysis gave back"."""

COLOUR_LEGEND_BACKGROUND = QColor(255, 255, 255, 236)
COLOUR_LEGEND_BORDER = QColor(196, 202, 209)

# -- geometry, all in device pixels ---------------------------------------------------------

BAND_WIDTH_PX = 9.0
BAND_ALPHA = 205
BAND_MARGIN_SCENE = 14.0
"""Scene-unit padding on the band's bounding rect.

The band is stroked with a cosmetic pen, so its true half-width in *scene* units grows without
limit as the view zooms out. A fixed scene margin therefore cannot be exact; this is a repaint
region only (Qt does not clip to boundingRect unless asked), so a generous constant is the
right trade rather than plumbing the view scale into a purely decorative overlay.
"""

LABEL_CLEARANCE_PX = 0.5 * BAND_WIDTH_PX + 3.0
"""Gap from the member axis to the *near edge* of the label chip.

Measured to the edge rather than to the chip centre because the chip's height depends on the
font, which depends on the platform and the display DPI. A fixed centre offset that clears the
band on one machine overlaps it on the next.
"""

LABEL_PAD_X_PX = 4.0
LABEL_PAD_Y_PX = 2.0
LABEL_FONT_PT = 8.0

REACTION_ARROW_MAX_PX = 46.0
REACTION_ARROW_MIN_PX = 14.0
REACTION_HEAD_LENGTH_PX = 9.0
REACTION_HEAD_HALF_WIDTH_PX = 3.6
REACTION_SHAFT_WIDTH_PX = 2.0
REACTION_LABEL_GAP_PX = 4.0
REACTION_LABEL_W_PX = 76.0
REACTION_LABEL_H_PX = 14.0
MOMENT_ARC_RADIUS_PX = 18.0
MOMENT_ARC_START_DEG = 35.0
MOMENT_ARC_SPAN_DEG = 250.0

LEGEND_W_PX = 176.0
LEGEND_H_PX = 84.0
LEGEND_PAD_PX = 9.0
LEGEND_RAMP_H_PX = 12.0
LEGEND_RAMP_STOPS = 21
LEGEND_TITLE_PT = 8.5
LEGEND_BODY_PT = 7.5


def member_force_colour(axial: float, max_abs_axial: float) -> QColor:
    """Colour for a member carrying ``axial`` newtons, tension positive (conventions section 6).

    Red is compression, blue is tension, grey is zero-force, and saturation rises with
    ``|axial| / max_abs_axial`` so the eye reads relative magnitude without consulting the
    legend.

    Hue alone must not carry the tension/compression distinction: red against blue is precisely
    the confusion axis for deuteranopia and protanopia, and it vanishes entirely in a greyscale
    print. So the two families are also given *disjoint lightness bands* - compression stays
    dark (HSL L 0.46 down to 0.34), tension stays light (0.72 down to 0.58). Any compression
    colour is darker than any tension colour, at every magnitude, which survives both colour
    blindness and a monochrome printer. The T/C suffix on the label is the third redundant cue.

    ``max_abs_axial <= 0`` is an unloaded or unsolved model, not an error: everything is grey.
    """
    if max_abs_axial <= 0.0:
        return QColor(COLOUR_ZERO_FORCE)

    ratio = min(1.0, abs(axial) / max_abs_axial)
    if ratio <= ZERO_FORCE_RATIO:
        return QColor(COLOUR_ZERO_FORCE)

    if axial < 0.0:
        hue_deg = HUE_COMPRESSION_DEG
        light_at_zero, light_at_peak = LIGHTNESS_COMPRESSION
    else:
        hue_deg = HUE_TENSION_DEG
        light_at_zero, light_at_peak = LIGHTNESS_TENSION

    saturation = SATURATION_MIN + (SATURATION_MAX - SATURATION_MIN) * ratio
    lightness = light_at_zero + (light_at_peak - light_at_zero) * ratio
    return QColor.fromHslF(hue_deg / 360.0, saturation, lightness)


def _force_decimals(value_si: float, units: UnitSystem) -> int:
    """Decimals that keep a force readable without pretending to precision it lacks.

    A truss result of 12500 N shown in kN wants "12.5", not "12.500" (noise) and not "13"
    (a lie about the last digit that a hand check would flag as wrong).
    """
    display = abs(units.force_from_si(value_si))
    if display >= 100.0:
        return 0
    if display >= 1.0:
        return 1
    if display >= 0.1:
        return 2
    return 3


def _moment_decimals(value_si: float, units: UnitSystem) -> int:
    display = abs(units.moment_from_si(value_si))
    if display >= 100.0:
        return 0
    if display >= 1.0:
        return 1
    if display >= 0.1:
        return 2
    return 3


def _overlay_font(point_size: float, bold: bool = False) -> QFont:
    """Build an annotation font.

    Never construct a ``QFont`` at module import time - it needs a live ``QGuiApplication``.
    """
    font = QFont()
    font.setPointSizeF(point_size)
    font.setBold(bold)
    return font


def _upright_angle_deg(dx: float, dy: float) -> float:
    """Rotation for text laid along a scene-space direction, kept readable left-to-right.

    ``dx``/``dy`` are scene deltas (Qt's +Y-down frame), so ``atan2`` here already gives the
    on-screen angle. A member drawn right-to-left has an angle past +/-90 degrees, and text at
    that angle reads upside down and backwards; folding it by 180 degrees keeps the label the
    right way up while it still runs parallel to the member. Vertical members fold to -90, so
    their labels read bottom-to-top, which is the usual drafting choice.
    """
    angle = math.degrees(math.atan2(dy, dx))
    if angle >= 90.0:
        angle -= 180.0
    elif angle < -90.0:
        angle += 180.0
    return angle


def _empty_shape() -> QPainterPath:
    """An empty hit area, so ``itemAt`` never returns a decoration instead of the real item."""
    return QPainterPath()


class _ForceLabelItem(QGraphicsItem):
    """The "12.5 kN C" chip riding beside a member.

    A child of ``MemberResultItem`` rather than part of its ``paint``: the band must scale with
    the drawing while the text must not, and one item cannot be in two coordinate systems.
    """

    def __init__(self, text: str, colour: QColor, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(1.0)
        self._font = _overlay_font(LABEL_FONT_PT)
        self._text = text
        self._colour = QColor(colour)
        self._chip = QRectF()
        self._measure()

    def _measure(self) -> None:
        """Size the chip from the current text. Device pixels, because of the ignore flag."""
        self.prepareGeometryChange()
        metrics = QFontMetricsF(self._font)
        width = metrics.horizontalAdvance(self._text) + 2.0 * LABEL_PAD_X_PX
        height = metrics.height() + 2.0 * LABEL_PAD_Y_PX
        self._chip = QRectF(
            -0.5 * width,
            -LABEL_CLEARANCE_PX - height,
            width,
            height,
        )

    def set_content(self, text: str, colour: QColor) -> None:
        self._text = text
        self._colour = QColor(colour)
        self._measure()
        self.update()

    def boundingRect(self) -> QRectF:
        return self._chip.adjusted(-1.5, -1.5, 1.5, 1.5)

    def shape(self) -> QPainterPath:
        return _empty_shape()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        border = QPen(self._colour)
        border.setWidthF(1.0)
        painter.setPen(border)
        painter.setBrush(QBrush(COLOUR_LABEL_BACKGROUND))
        painter.drawRoundedRect(self._chip, 3.0, 3.0)

        painter.setFont(self._font)
        painter.setPen(QPen(COLOUR_LABEL_TEXT))
        painter.drawText(self._chip, Qt.AlignmentFlag.AlignCenter, self._text)


class MemberResultItem(QGraphicsItem):
    """The force band and force label for one solved member.

    ``p1``/``p2`` arrive already in scene coordinates - the caller has run them through
    ``coords.to_scene``. Taking model metres here would mean a second place that knows about
    the Y flip, and conventions section 2 allows exactly one.
    """

    def __init__(
        self,
        member_id: int,
        p1: QPointF,
        p2: QPointF,
        result: MemberResult,
        max_abs_axial: float,
        units: UnitSystem,
    ) -> None:
        super().__init__()
        self.member_id = member_id
        self.setZValue(RESULT_BAND_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        self._p1 = QPointF(p1)
        self._p2 = QPointF(p2)
        self._result = result
        self._max_abs_axial = max_abs_axial
        self._units = units
        self._colour = member_force_colour(result.axial, max_abs_axial)
        self._label = _ForceLabelItem(self._format_label(), self._colour, self)
        self._place_label()

    # -- content --------------------------------------------------------

    @property
    def result(self) -> MemberResult:
        return self._result

    @property
    def colour(self) -> QColor:
        return QColor(self._colour)

    def _format_label(self) -> str:
        """Magnitude plus a T/C marker - the sign lives in the marker, not in a minus sign.

        "-12.5 kN" would be read as "negative force" rather than "compression", and the sign
        convention (tension positive) is not something a drawing can state in passing.
        """
        axial = self._result.axial
        if self._result.state is MemberState.ZERO:
            return f"0 {self._units.force}"
        magnitude = self._units.format_force(abs(axial), _force_decimals(axial, self._units))
        marker = "C" if self._result.state is MemberState.COMPRESSION else "T"
        return f"{magnitude} {marker}"

    def update_result(
        self,
        result: MemberResult,
        max_abs_axial: float,
        units: UnitSystem | None = None,
    ) -> None:
        """Re-point at a fresh analysis without rebuilding the scene."""
        self.prepareGeometryChange()
        self._result = result
        self._max_abs_axial = max_abs_axial
        if units is not None:
            self._units = units
        self._colour = member_force_colour(result.axial, max_abs_axial)
        self._label.set_content(self._format_label(), self._colour)
        self.update()

    def update_endpoints(self, p1: QPointF, p2: QPointF) -> None:
        """Follow the member after a node move. Scene coordinates, as in the constructor."""
        self.prepareGeometryChange()
        self._p1 = QPointF(p1)
        self._p2 = QPointF(p2)
        self._place_label()
        self.update()

    # -- geometry -------------------------------------------------------

    def _place_label(self) -> None:
        dx = self._p2.x() - self._p1.x()
        dy = self._p2.y() - self._p1.y()
        midpoint = QPointF(
            0.5 * (self._p1.x() + self._p2.x()),
            0.5 * (self._p1.y() + self._p2.y()),
        )
        self._label.setPos(midpoint)
        # The chip is drawn wholly at local -y, i.e. clear of the member on one side, so the
        # text never sits on the line it describes.
        self._label.setRotation(_upright_angle_deg(dx, dy))

    def boundingRect(self) -> QRectF:
        return (
            QRectF(self._p1, self._p2)
            .normalized()
            .adjusted(
                -BAND_MARGIN_SCENE,
                -BAND_MARGIN_SCENE,
                BAND_MARGIN_SCENE,
                BAND_MARGIN_SCENE,
            )
        )

    def shape(self) -> QPainterPath:
        return _empty_shape()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        band = QColor(self._colour)
        band.setAlpha(BAND_ALPHA)
        pen = QPen(band)
        pen.setCosmetic(True)  # constant device width at every zoom, exactly like MemberItem
        pen.setWidthF(BAND_WIDTH_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(self._p1, self._p2)


class ReactionItem(QGraphicsItem):
    """Support reaction arrows at one node.

    Positioned by the caller with ``setPos(*coords.to_scene(node.x, node.y))``, matching
    ``NodeItem``: the item knows a node id and a result, never a coordinate in metres.
    """

    def __init__(
        self,
        node_id: int,
        result: ReactionResult,
        reference: float,
        units: UnitSystem,
    ) -> None:
        super().__init__()
        self.node_id = node_id
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(REACTION_Z)
        self._result = result
        self._reference = reference
        self._units = units
        self._font = _overlay_font(LABEL_FONT_PT)

    @property
    def result(self) -> ReactionResult:
        return self._result

    def update_result(
        self,
        result: ReactionResult,
        reference: float,
        units: UnitSystem | None = None,
    ) -> None:
        self.prepareGeometryChange()
        self._result = result
        self._reference = reference
        if units is not None:
            self._units = units
        self.update()

    # -- scaling --------------------------------------------------------

    def _arrow_length(self, magnitude: float) -> float:
        """Pixel length for a reaction of ``magnitude`` newtons.

        Scaled against ``reference`` (the largest reaction in the model), which maps the biggest
        arrow to a fixed pixel length. Scaling linearly with newtons instead would put a 500 kN
        reaction several screens away, and would make the same structure look different purely
        because its loads were entered in different units.
        """
        if self._reference <= 0.0:
            return REACTION_ARROW_MIN_PX
        fraction = min(1.0, abs(magnitude) / self._reference)
        span = REACTION_ARROW_MAX_PX - REACTION_ARROW_MIN_PX
        return REACTION_ARROW_MIN_PX + span * fraction

    def _negligible(self, value: float) -> bool:
        """True for a component that is zero to within solver noise, so it is not drawn."""
        return abs(value) <= max(abs(self._reference), 1.0) * 1.0e-6

    # -- geometry -------------------------------------------------------

    def boundingRect(self) -> QRectF:
        """Device pixels: this item ignores the view transform."""
        half_w = REACTION_ARROW_MAX_PX + REACTION_LABEL_GAP_PX + REACTION_LABEL_W_PX
        half_h = (
            REACTION_ARROW_MAX_PX
            + REACTION_LABEL_GAP_PX
            + REACTION_LABEL_H_PX
            + MOMENT_ARC_RADIUS_PX
        )
        return QRectF(-half_w, -half_h, 2.0 * half_w, 2.0 * half_h)

    def shape(self) -> QPainterPath:
        return _empty_shape()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._font)

        # A reaction is the force the SUPPORT EXERTS ON THE STRUCTURE (conventions section 10),
        # so a positive fy acts UP in model space. Model +Y is up, scene/device +Y is down, so
        # up on screen is -y here. Getting this backwards is the likely bug in this class: the
        # arrows would appear to drag the structure downwards at every support.
        fy = self._result.fy
        if not self._negligible(fy):
            direction = QPointF(0.0, -1.0) if fy > 0.0 else QPointF(0.0, 1.0)
            self._draw_arrow(painter, direction, abs(fy), horizontal=False)

        # +X is right in both frames; no flip applies to the horizontal component.
        fx = self._result.fx
        if not self._negligible(fx):
            direction = QPointF(1.0, 0.0) if fx > 0.0 else QPointF(-1.0, 0.0)
            self._draw_arrow(painter, direction, abs(fx), horizontal=True)

        # Truss mode auto-constrains every rz DOF, so the value recovered there is identically
        # zero and is NOT a physical reaction (conventions section 3). Drawing "0.0" for it
        # would be a claim the analysis never made.
        if self._result.has_moment and not self._negligible(self._result.mz):
            self._draw_moment(painter, self._result.mz)

    def _draw_arrow(
        self,
        painter: QPainter,
        direction: QPointF,
        magnitude: float,
        horizontal: bool,
    ) -> None:
        """Arrowhead at the node, tail away from it - the force acts *into* the joint."""
        length = self._arrow_length(magnitude)
        tip = QPointF(0.0, 0.0)
        tail = QPointF(-direction.x() * length, -direction.y() * length)

        shaft = QPen(COLOUR_REACTION)
        shaft.setWidthF(REACTION_SHAFT_WIDTH_PX)
        shaft.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(shaft)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(tail, tip)

        # Perpendicular of (dx, dy) is (-dy, dx) - direction is a unit vector, so no norm.
        base = QPointF(
            tip.x() - direction.x() * REACTION_HEAD_LENGTH_PX,
            tip.y() - direction.y() * REACTION_HEAD_LENGTH_PX,
        )
        perp = QPointF(-direction.y(), direction.x())
        head = QPolygonF(
            [
                tip,
                QPointF(
                    base.x() + perp.x() * REACTION_HEAD_HALF_WIDTH_PX,
                    base.y() + perp.y() * REACTION_HEAD_HALF_WIDTH_PX,
                ),
                QPointF(
                    base.x() - perp.x() * REACTION_HEAD_HALF_WIDTH_PX,
                    base.y() - perp.y() * REACTION_HEAD_HALF_WIDTH_PX,
                ),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(COLOUR_REACTION))
        painter.drawPolygon(head)

        clearance = REACTION_LABEL_GAP_PX + 0.5 * (
            REACTION_LABEL_W_PX if horizontal else REACTION_LABEL_H_PX
        )
        centre = QPointF(
            tail.x() - direction.x() * clearance,
            tail.y() - direction.y() * clearance,
        )
        text = self._units.format_force(magnitude, _force_decimals(magnitude, self._units))
        self._draw_text(painter, centre, REACTION_LABEL_W_PX, text)

    def _draw_moment(self, painter: QPainter, mz: float) -> None:
        """Curved arrow for a reaction moment, CCW positive (conventions section 2).

        Qt measures arc angles anticlockwise *as displayed*, and the scene's Y flip is what
        makes the drawing look like the model, so a CCW model moment is a positive span here.
        """
        span = MOMENT_ARC_SPAN_DEG if mz > 0.0 else -MOMENT_ARC_SPAN_DEG
        box = QRectF(
            -MOMENT_ARC_RADIUS_PX,
            -MOMENT_ARC_RADIUS_PX,
            2.0 * MOMENT_ARC_RADIUS_PX,
            2.0 * MOMENT_ARC_RADIUS_PX,
        )
        pen = QPen(COLOUR_REACTION)
        pen.setWidthF(REACTION_SHAFT_WIDTH_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(box, round(MOMENT_ARC_START_DEG * 16), round(span * 16))

        end_deg = MOMENT_ARC_START_DEG + span
        end_rad = math.radians(end_deg)
        # Qt's arc angle t maps to (r cos t, -r sin t) in this Y-down frame.
        tip = QPointF(
            MOMENT_ARC_RADIUS_PX * math.cos(end_rad),
            -MOMENT_ARC_RADIUS_PX * math.sin(end_rad),
        )
        sweep = 1.0 if span > 0.0 else -1.0
        tangent = QPointF(-math.sin(end_rad) * sweep, -math.cos(end_rad) * sweep)
        base = QPointF(
            tip.x() - tangent.x() * REACTION_HEAD_LENGTH_PX,
            tip.y() - tangent.y() * REACTION_HEAD_LENGTH_PX,
        )
        perp = QPointF(-tangent.y(), tangent.x())
        head = QPolygonF(
            [
                tip,
                QPointF(
                    base.x() + perp.x() * REACTION_HEAD_HALF_WIDTH_PX,
                    base.y() + perp.y() * REACTION_HEAD_HALF_WIDTH_PX,
                ),
                QPointF(
                    base.x() - perp.x() * REACTION_HEAD_HALF_WIDTH_PX,
                    base.y() - perp.y() * REACTION_HEAD_HALF_WIDTH_PX,
                ),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(COLOUR_REACTION))
        painter.drawPolygon(head)

        # Down-right of the joint: the vertical force label sits straight below it, and a
        # support symbol usually occupies the space directly under a fixed node.
        offset = MOMENT_ARC_RADIUS_PX + REACTION_LABEL_GAP_PX
        centre = QPointF(offset + 0.5 * REACTION_LABEL_W_PX, offset)
        text = self._units.format_moment(abs(mz), _moment_decimals(mz, self._units))
        self._draw_text(painter, centre, REACTION_LABEL_W_PX, text)

    def _draw_text(self, painter: QPainter, centre: QPointF, width: float, text: str) -> None:
        box = QRectF(
            centre.x() - 0.5 * width,
            centre.y() - 0.5 * REACTION_LABEL_H_PX,
            width,
            REACTION_LABEL_H_PX,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(COLOUR_LABEL_BACKGROUND))
        painter.drawRoundedRect(box.adjusted(-2.0, -1.0, 2.0, 1.0), 3.0, 3.0)
        painter.setPen(QPen(COLOUR_REACTION))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class DiagramLegendItem(QGraphicsItem):
    """Key for the member force ramp, pinned in a corner of the view.

    The item cannot pin itself - it has no view - so the caller keeps ``setPos`` in step with
    the viewport corner. It ignores transformations, so that position is the only thing that
    ever has to be recomputed on zoom or pan.
    """

    def __init__(self, max_abs_axial: float, units: UnitSystem) -> None:
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(LEGEND_Z)
        self._max_abs_axial = max_abs_axial
        self._units = units
        self._title_font = _overlay_font(LEGEND_TITLE_PT, bold=True)
        self._body_font = _overlay_font(LEGEND_BODY_PT)

    def update_scale(self, max_abs_axial: float, units: UnitSystem | None = None) -> None:
        """Follow a new analysis. The box is a fixed size, so no geometry change is needed."""
        self._max_abs_axial = max_abs_axial
        if units is not None:
            self._units = units
        self.update()

    def boundingRect(self) -> QRectF:
        """Device pixels, anchored at the item origin (its top-left corner)."""
        return QRectF(0.0, 0.0, LEGEND_W_PX, LEGEND_H_PX).adjusted(-1.0, -1.0, 1.0, 1.0)

    def shape(self) -> QPainterPath:
        return _empty_shape()

    def _ramp(self, rect: QRectF) -> QLinearGradient:
        """Sample the very function the members use, so the key can never drift from the map."""
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        if self._max_abs_axial <= 0.0:
            gradient.setColorAt(0.0, COLOUR_ZERO_FORCE)
            gradient.setColorAt(1.0, COLOUR_ZERO_FORCE)
            return gradient
        for index in range(LEGEND_RAMP_STOPS):
            position = index / (LEGEND_RAMP_STOPS - 1)
            signed = (2.0 * position - 1.0) * self._max_abs_axial
            gradient.setColorAt(position, member_force_colour(signed, self._max_abs_axial))
        return gradient

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        frame = QRectF(0.0, 0.0, LEGEND_W_PX, LEGEND_H_PX)
        painter.setPen(QPen(COLOUR_LEGEND_BORDER))
        painter.setBrush(QBrush(COLOUR_LEGEND_BACKGROUND))
        painter.drawRoundedRect(frame, 4.0, 4.0)

        inner_w = LEGEND_W_PX - 2.0 * LEGEND_PAD_PX
        cursor = LEGEND_PAD_PX

        painter.setFont(self._title_font)
        painter.setPen(QPen(COLOUR_LABEL_TEXT))
        title = QRectF(LEGEND_PAD_PX, cursor, inner_w, 14.0)
        painter.drawText(title, Qt.AlignmentFlag.AlignLeft, "Member axial force")
        cursor += 17.0

        ramp = QRectF(LEGEND_PAD_PX, cursor, inner_w, LEGEND_RAMP_H_PX)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._ramp(ramp)))
        painter.drawRect(ramp)
        painter.setPen(QPen(COLOUR_LEGEND_BORDER))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(ramp)
        cursor += LEGEND_RAMP_H_PX + 2.0

        painter.setFont(self._body_font)
        painter.setPen(QPen(COLOUR_LABEL_TEXT))
        ends = QRectF(LEGEND_PAD_PX, cursor, inner_w, 13.0)
        painter.drawText(ends, Qt.AlignmentFlag.AlignLeft, "Compression")
        painter.drawText(ends, Qt.AlignmentFlag.AlignRight, "Tension")
        cursor += 15.0

        peak = QRectF(LEGEND_PAD_PX, cursor, inner_w, 13.0)
        if self._max_abs_axial <= 0.0:
            summary = "No member forces"
        else:
            value = self._units.format_force(
                self._max_abs_axial, _force_decimals(self._max_abs_axial, self._units)
            )
            summary = f"Peak {value}"
        painter.drawText(peak, Qt.AlignmentFlag.AlignLeft, summary)


__all__ = [
    "BAND_WIDTH_PX",
    "COLOUR_REACTION",
    "COLOUR_ZERO_FORCE",
    "LEGEND_Z",
    "REACTION_ARROW_MAX_PX",
    "REACTION_Z",
    "RESULT_BAND_Z",
    "DiagramLegendItem",
    "MemberResultItem",
    "ReactionItem",
    "member_force_colour",
]
