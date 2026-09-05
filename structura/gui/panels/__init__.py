"""Docked panels: properties and the model tree.

Both are strictly views onto the document. Every edit they offer goes out as a command, so
anything changed here is undoable exactly like a canvas edit.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ..commands import MoveNodesCommand, SetMemberPropertyCommand
from ..document import Document

COORD_RANGE = 1.0e6
COORD_DECIMALS = 4


class PropertiesDock(QDockWidget):
    """Shows and edits whatever is selected."""

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__("Properties", parent)
        self.document = document
        self.setObjectName("PropertiesDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._node_ids: list[int] = []
        self._member_ids: list[int] = []
        self._updating = False

        body = QWidget()
        self._form = QFormLayout(body)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._summary = QLabel("Nothing selected")
        self._summary.setWordWrap(True)
        self._form.addRow(self._summary)

        self._x = self._coord_spin()
        self._y = self._coord_spin()
        self._form.addRow("X (m)", self._x)
        self._form.addRow("Y (m)", self._y)

        self._length = QLabel("-")
        self._angle = QLabel("-")
        self._form.addRow("Length (m)", self._length)
        self._form.addRow("Angle (deg)", self._angle)

        self._section = QComboBox()
        self._material = QComboBox()
        self._form.addRow("Section", self._section)
        self._form.addRow("Material", self._material)

        self._x.valueChanged.connect(self._commit_position)
        self._y.valueChanged.connect(self._commit_position)
        self._section.activated.connect(self._commit_section)
        self._material.activated.connect(self._commit_material)

        self.setWidget(body)
        self.show_selection([], [])

    def _coord_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-COORD_RANGE, COORD_RANGE)
        spin.setDecimals(COORD_DECIMALS)
        spin.setSingleStep(0.1)
        spin.setKeyboardTracking(False)  # commit on Enter/focus-out, not per keystroke
        return spin

    # ------------------------------------------------------------------ display

    def show_selection(self, node_ids: list[int], member_ids: list[int]) -> None:
        """Re-read the model for the current selection."""
        self._updating = True
        try:
            self._node_ids = node_ids
            self._member_ids = member_ids
            structure = self.document.structure

            node_rows = len(node_ids) == 1 and not member_ids
            member_rows = len(member_ids) == 1 and not node_ids

            self._set_row_visible(self._x, node_rows)
            self._set_row_visible(self._y, node_rows)
            self._set_row_visible(self._length, member_rows)
            self._set_row_visible(self._angle, member_rows)
            self._set_row_visible(self._section, member_rows)
            self._set_row_visible(self._material, member_rows)

            if node_rows:
                node = structure.nodes.get(node_ids[0])
                if node is not None:
                    self._summary.setText(f"Node {node.id}")
                    self._x.setValue(node.x)
                    self._y.setValue(node.y)
            elif member_rows:
                self._populate_member(member_ids[0])
            else:
                self._summary.setText(self._describe_multi(node_ids, member_ids))
        finally:
            self._updating = False

    def _describe_multi(self, node_ids: list[int], member_ids: list[int]) -> str:
        if not node_ids and not member_ids:
            return "Nothing selected"
        parts = []
        if node_ids:
            parts.append(f"{len(node_ids)} node" + ("s" if len(node_ids) != 1 else ""))
        if member_ids:
            parts.append(f"{len(member_ids)} member" + ("s" if len(member_ids) != 1 else ""))
        return " and ".join(parts) + " selected"

    def _populate_member(self, member_id: int) -> None:
        structure = self.document.structure
        member = structure.members.get(member_id)
        if member is None:
            return
        geo = structure.member_geometry(member_id)
        self._summary.setText(
            f"Member {member.id}  (node {member.node_i} to node {member.node_j})"
        )
        self._length.setText(f"{geo.length:.4f}")
        self._angle.setText(f"{geo.angle_deg:.2f}")

        self._section.clear()
        for section_id in sorted(structure.sections):
            section = structure.sections[section_id]
            self._section.addItem(f"{section.name} (A={section.area:g})", section_id)
        self._select_data(self._section, member.section_id)

        self._material.clear()
        for material_id in sorted(structure.materials):
            material = structure.materials[material_id]
            self._material.addItem(f"{material.name} (E={material.E:g})", material_id)
        self._select_data(self._material, member.material_id)

    @staticmethod
    def _select_data(combo: QComboBox, value: int) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_row_visible(self, widget: QWidget, visible: bool) -> None:
        label = self._form.labelForField(widget)
        widget.setVisible(visible)
        if label is not None:
            label.setVisible(visible)

    # ------------------------------------------------------------------ edits

    def _commit_position(self) -> None:
        if self._updating or len(self._node_ids) != 1:
            return
        node = self.document.structure.nodes.get(self._node_ids[0])
        if node is None:
            return
        start = (node.x, node.y)
        end = (self._x.value(), self._y.value())
        if start == end:
            return
        self.document.push(MoveNodesCommand(self.document, {node.id: (start, end)}))

    def _commit_section(self) -> None:
        if self._updating or not self._member_ids:
            return
        value = self._section.currentData()
        if value is not None:
            self.document.push(
                SetMemberPropertyCommand(self.document, self._member_ids, "section_id", value)
            )

    def _commit_material(self) -> None:
        if self._updating or not self._member_ids:
            return
        value = self._material.currentData()
        if value is not None:
            self.document.push(
                SetMemberPropertyCommand(self.document, self._member_ids, "material_id", value)
            )


class ModelTreeDock(QDockWidget):
    """A list of every joint and member. Clicking an entry selects it on the canvas."""

    selectionRequested = Signal(list, list)
    """Emitted with (node_ids, member_ids) when the user picks entries here."""

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__("Model", parent)
        self.document = document
        self.setObjectName("ModelTreeDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._updating = False
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Item", "Detail"])
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.setWidget(self.tree)

        self._nodes_root = QTreeWidgetItem(self.tree, ["Nodes", ""])
        self._members_root = QTreeWidgetItem(self.tree, ["Members", ""])
        self._nodes_root.setExpanded(True)
        self._members_root.setExpanded(True)

        document.modelChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Rebuild from the model. Selection is restored by the window, not preserved here."""
        self._updating = True
        try:
            structure = self.document.structure
            self._nodes_root.takeChildren()
            self._members_root.takeChildren()

            for node_id in sorted(structure.nodes):
                node = structure.nodes[node_id]
                item = QTreeWidgetItem(
                    self._nodes_root, [f"Node {node_id}", f"({node.x:g}, {node.y:g})"]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, ("node", node_id))

            for member_id in sorted(structure.members):
                member = structure.members[member_id]
                try:
                    length = structure.member_length(member_id)
                    detail = f"{member.node_i}-{member.node_j}   {length:.3f} m"
                except (KeyError, ValueError):
                    detail = f"{member.node_i}-{member.node_j}"
                item = QTreeWidgetItem(self._members_root, [f"Member {member_id}", detail])
                item.setData(0, Qt.ItemDataRole.UserRole, ("member", member_id))

            self._nodes_root.setText(1, f"{len(structure.nodes)} total")
            self._members_root.setText(1, f"{len(structure.members)} total")
        finally:
            self._updating = False

    def show_selection(self, node_ids: list[int], member_ids: list[int]) -> None:
        """Mirror the canvas selection into the tree without echoing it back."""
        self._updating = True
        try:
            wanted = {("node", n) for n in node_ids} | {("member", m) for m in member_ids}
            for root in (self._nodes_root, self._members_root):
                for index in range(root.childCount()):
                    child = root.child(index)
                    child.setSelected(child.data(0, Qt.ItemDataRole.UserRole) in wanted)
        finally:
            self._updating = False

    def _on_tree_selection(self) -> None:
        if self._updating:
            return
        node_ids: list[int] = []
        member_ids: list[int] = []
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            kind, identifier = data
            (node_ids if kind == "node" else member_ids).append(identifier)
        self.selectionRequested.emit(node_ids, member_ids)


__all__ = ["ModelTreeDock", "PropertiesDock"]
