"""The viewport: zoom, pan and fit.

Zoom is clamped well beyond the range the Phase 3 gate asks for (0.01x to 100x). Qt's
transforms round-trip exactly across that span - verified - so the limits exist to keep the
drawing comprehensible rather than to dodge a numerical cliff.

Panning is on the middle mouse button, and on the left button while space is held. The left
button alone always belongs to the active tool, so drawing is never ambiguous.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsView

from . import coords
from .canvas_scene import CanvasScene

MIN_SCALE = 0.005
MAX_SCALE = 200.0
ZOOM_STEP = 1.15
"""Per wheel notch. Gentle enough to land on a chosen zoom without overshooting."""

FIT_MARGIN = 1.08
"""Fit-to-extents leaves a little air so nothing touches the frame."""


class CanvasView(QGraphicsView):
    """Graphics view with CAD-style navigation."""

    def __init__(self, scene: CanvasScene) -> None:
        super().__init__(scene)
        self.canvas = scene

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._panning = False
        self._space_held = False
        self._pan_origin = QPoint()

        self._publish_scale()

    # ------------------------------------------------------------------ zoom

    @property
    def scale_factor(self) -> float:
        """Device pixels per scene unit."""
        return float(self.transform().m11())

    def _publish_scale(self) -> None:
        self.canvas.set_view_scale(self.scale_factor)

    def zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:
        """Multiply the zoom, keeping the point under ``anchor`` stationary."""
        target = self.scale_factor * factor
        clamped = max(MIN_SCALE, min(MAX_SCALE, target))
        if clamped == self.scale_factor:
            return
        factor = clamped / self.scale_factor

        if anchor is None:
            anchor = self.viewport().rect().center()
        before = self.mapToScene(anchor)
        self.scale(factor, factor)
        after = self.mapToScene(anchor)
        delta = after - before
        self.translate(delta.x(), delta.y())

        self._publish_scale()

    def zoom_in(self) -> None:
        self.zoom_by(ZOOM_STEP)

    def zoom_out(self) -> None:
        self.zoom_by(1.0 / ZOOM_STEP)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._publish_scale()

    def fit_to_model(self) -> None:
        """Frame the whole structure. Falls back to a sensible default when it is empty."""
        structure = self.canvas.structure
        if not structure.nodes:
            self.reset_zoom()
            self.centerOn(0.0, 0.0)
            return

        xmin, ymin, xmax, ymax = structure.bounds()
        left, top = coords.to_scene(xmin, ymax)
        right, bottom = coords.to_scene(xmax, ymin)
        width = max(right - left, coords.scene_length(1.0))
        height = max(bottom - top, coords.scene_length(1.0))

        cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
        viewport = self.viewport().rect()
        scale = min(viewport.width() / (width * FIT_MARGIN),
                    viewport.height() / (height * FIT_MARGIN))
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))

        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(cx, cy)
        self._publish_scale()

    def wheelEvent(self, event: QWheelEvent) -> None:
        notches = event.angleDelta().y() / 120.0
        if notches:
            self.zoom_by(ZOOM_STEP**notches, event.position().toPoint())
        event.accept()

    # ------------------------------------------------------------------ pan

    def _pan_requested(self, event: QMouseEvent) -> bool:
        if event.button() == Qt.MouseButton.MiddleButton:
            return True
        return event.button() == Qt.MouseButton.LeftButton and self._space_held

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._pan_requested(event):
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position().toPoint() - self._pan_origin
            self._pan_origin = event.position().toPoint()
            # Scroll bars move opposite to the drag, so content follows the cursor.
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and (
            event.button() == Qt.MouseButton.MiddleButton
            or event.button() == Qt.MouseButton.LeftButton
        ):
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ keys

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            if not self._panning:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def event(self, event: QEvent) -> bool:
        """Drop the space-pan latch if the window loses focus mid-press."""
        if event.type() == QEvent.Type.WindowDeactivate:
            self._space_held = False
            self._panning = False
        return super().event(event)
