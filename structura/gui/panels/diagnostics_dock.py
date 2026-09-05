"""Diagnostics dock: the validation and analysis messages, made clickable.

This is a **view**. It computes nothing: the ``Diagnostic`` list and the ``EquilibriumCheck``
are produced by the core and only rendered here.

The point of the dock is the click. ``Diagnostic`` carries ``node_ids`` and ``member_ids``
precisely so a message can be turned into a selection, and this dock is what spends them:
picking a row emits ``selectionRequested`` and the main window selects and zooms to the
offending joint or member. Without that, an error message is a complaint; with it, it is a
place to go.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHeaderView,
    QLabel,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.analysis import EquilibriumCheck
from ...core.model import Severity
from ...core.validation import Diagnostic

SEVERITY_COLOURS: dict[Severity, QColor] = {
    Severity.ERROR: QColor("#a3231a"),
    Severity.WARNING: QColor("#8a5b00"),
    Severity.INFO: QColor("#3a4e64"),
}

SEVERITY_ICONS: dict[Severity, QStyle.StandardPixmap] = {
    Severity.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
    Severity.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Severity.INFO: QStyle.StandardPixmap.SP_MessageBoxInformation,
}

SEVERITY_ORDER: tuple[Severity, ...] = (Severity.ERROR, Severity.WARNING, Severity.INFO)

PASS_COLOUR = "#1d6b3a"
FAIL_COLOUR = "#a3231a"

NO_PROBLEMS = "No problems found."

PAYLOAD_ROLE = Qt.ItemDataRole.UserRole
"""Each row carries its own (node_ids, member_ids) so child rows are clickable too."""


class DiagnosticsDock(QDockWidget):
    """Lists analysis diagnostics. Clicking one asks the window to select what it refers to."""

    selectionRequested = Signal(list, list)
    """Emitted with (node_ids, member_ids) from the diagnostic the user picked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Diagnostics", parent)
        self.setObjectName("DiagnosticsDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._updating = False

        body = QWidget()
        layout = QVBoxLayout(body)

        self._summary = QLabel(NO_PROBLEMS)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Severity", "Code", "Message"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # Selection change covers mouse and keyboard; double click re-emits so the user can
        # zoom back to a row that is already selected.
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        layout.addWidget(self.tree, 1)

        self._equilibrium = QLabel()
        self._equilibrium.setWordWrap(True)
        self._equilibrium.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._equilibrium.hide()
        layout.addWidget(self._equilibrium)

        self.setWidget(body)

    # ------------------------------------------------------------------ display

    def show_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        """Replace the list. Order is the core's, not ours - it reports in discovery order."""
        self._updating = True
        try:
            self.tree.clear()
            for diagnostic in diagnostics:
                self._add_row(diagnostic)
            self._summary.setText(self._describe(diagnostics))
        finally:
            self._updating = False

    def clear(self) -> None:
        """Reset the whole dock, equilibrium line included - stale verdicts mislead."""
        self._updating = True
        try:
            self.tree.clear()
            self._summary.setText(NO_PROBLEMS)
            self._equilibrium.clear()
            self._equilibrium.hide()
        finally:
            self._updating = False

    def show_equilibrium(self, check: EquilibriumCheck | None) -> None:
        """Show the post-solve self-check.

        A failed check is not a modelling mistake the user can fix: applied loads and
        reactions failing to sum to zero means the assembly, transformation or reaction
        recovery is wrong. It is worded as a solver bug because that is what it is.
        """
        if check is None:
            self._equilibrium.clear()
            self._equilibrium.hide()
            return

        if check.passed:
            colour = PASS_COLOUR
            lines = [f"Equilibrium check: PASSED   ({check.summary()})"]
        else:
            colour = FAIL_COLOUR
            lines = [
                f"Equilibrium check: FAILED   ({check.summary()})",
                "This is a bug in the solver, not a mistake in your model. The results "
                "above cannot be trusted - please report it.",
            ]
        self._equilibrium.setStyleSheet(f"color: {colour}; font-weight: bold;")
        self._equilibrium.setText("\n".join(lines))
        self._equilibrium.show()

    # ------------------------------------------------------------------ rows

    def _add_row(self, diagnostic: Diagnostic) -> None:
        severity = diagnostic.severity
        item = QTreeWidgetItem(
            self.tree,
            [severity.value.upper(), diagnostic.code, diagnostic.message],
        )
        colour = SEVERITY_COLOURS.get(severity)
        if colour is not None:
            brush = QBrush(colour)
            for column in range(self.tree.columnCount()):
                item.setForeground(column, brush)
        item.setIcon(0, self._icon(severity))
        item.setToolTip(2, self._tooltip(diagnostic))
        payload = (list(diagnostic.node_ids), list(diagnostic.member_ids))
        item.setData(0, PAYLOAD_ROLE, payload)

        if diagnostic.hint:
            hint = QTreeWidgetItem(item, ["", "", f"Hint: {diagnostic.hint}"])
            hint.setToolTip(2, diagnostic.hint)
            hint.setData(0, PAYLOAD_ROLE, payload)  # clicking the hint targets the same items
            item.setExpanded(True)

    def _icon(self, severity: Severity) -> QIcon:
        pixmap = SEVERITY_ICONS.get(severity, QStyle.StandardPixmap.SP_MessageBoxInformation)
        return self.style().standardIcon(pixmap)

    @staticmethod
    def _tooltip(diagnostic: Diagnostic) -> str:
        parts = [diagnostic.message]
        if diagnostic.hint:
            parts.append(diagnostic.hint)
        targets: list[str] = []
        if diagnostic.node_ids:
            targets.append("nodes " + ", ".join(str(n) for n in diagnostic.node_ids))
        if diagnostic.member_ids:
            targets.append("members " + ", ".join(str(m) for m in diagnostic.member_ids))
        if targets:
            parts.append("Click to select " + " and ".join(targets) + ".")
        return "\n\n".join(parts)

    @staticmethod
    def _describe(diagnostics: list[Diagnostic]) -> str:
        if not diagnostics:
            return NO_PROBLEMS
        counts = {severity: 0 for severity in SEVERITY_ORDER}
        for diagnostic in diagnostics:
            if diagnostic.severity in counts:
                counts[diagnostic.severity] += 1
        parts = [
            f"{count} {severity.value}" + ("s" if count != 1 else "")
            for severity, count in counts.items()
            if count
        ]
        return ", ".join(parts) if parts else NO_PROBLEMS

    # ------------------------------------------------------------------ clicks

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        items = self.tree.selectedItems()
        if items:
            self._emit_for(items[0])

    def _on_item_activated(self, item: QTreeWidgetItem, column: int) -> None:
        del column  # the whole row means the same thing
        self._emit_for(item)

    def _emit_for(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, PAYLOAD_ROLE)
        if not payload:
            return
        node_ids, member_ids = payload
        if not node_ids and not member_ids:
            # A general message names nothing; wiping the user's selection would be a loss.
            return
        self.selectionRequested.emit(list(node_ids), list(member_ids))


__all__ = ["DiagnosticsDock"]
