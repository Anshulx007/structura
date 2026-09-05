"""Member detail dialog: everything known about one member after analysis.

This is a **view**. It never computes a force, a stress or an elongation: every physical
number on screen is read straight off the ``MemberResult`` the solver produced, and the only
arithmetic performed here is display-unit conversion, which is delegated to ``UnitSystem``.
If a value cannot be found in the result it is shown as "-" rather than derived, because a
number the solver did not produce is a number nobody has checked.

Geometry that is not a result - the joint coordinates - comes from the ``Structure``, since
the model is the authority on where a joint is.

The dialog is deliberately non-modal and retargetable (``show_member``): the user clicks
member after member, and each click should update this window rather than stack another one.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.analysis import AnalysisResult, MemberResult
from ...core.model import AnalysisType, MemberState, Structure
from ...core.units import UnitSystem

MISSING = "-"
"""Shown wherever the result has nothing to say. Never a zero: zero is a claim."""

BADGE_COLOURS: dict[MemberState, tuple[str, str]] = {
    MemberState.TENSION: ("#0b4f8a", "#dcebf8"),
    MemberState.COMPRESSION: ("#8f1d14", "#fadedb"),
    MemberState.ZERO: ("#4a5560", "#e6e8ea"),
}
"""(text colour, background colour) per state. Tension blue, compression red, zero grey."""

BADGE_STYLE = (
    "color: {fg}; background-color: {bg}; border: 1px solid {fg};"
    " border-radius: 4px; padding: 8px 14px; font-size: 16pt; font-weight: bold;"
)

END_FORCE_ROWS: tuple[tuple[str, int, int], ...] = (
    ("Axial N", 0, 3),
    ("Shear V", 1, 4),
    ("Moment M", 2, 5),
)
"""Row label plus the indices into ``end_forces_local`` = [N_i, V_i, M_i, N_j, V_j, M_j]."""


class MemberDetailDialog(QDialog):
    """Full report for one member: geometry, properties, axial state and end forces."""

    def __init__(
        self,
        member_id: int,
        result: AnalysisResult,
        structure: Structure,
        units: UnitSystem,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.structure = structure
        self.units = units
        self._member_id = member_id
        self._result = result

        self.setModal(False)  # the user keeps clicking members while this stays open
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)

        self._heading = QLabel()
        self._heading.setStyleSheet("font-size: 13pt; font-weight: bold;")
        layout.addWidget(self._heading)

        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._badge)

        form_host = QWidget()
        self._form = QFormLayout(form_host)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(form_host)

        self._joints = self._value_label()
        self._length = self._value_label()
        self._angle = self._value_label()
        self._material = self._value_label()
        self._section = self._value_label()
        self._axial = self._value_label()
        self._stress = self._value_label()
        self._elongation = self._value_label()

        self._form.addRow("Joints", self._joints)
        self._form.addRow("Length", self._length)
        self._form.addRow("Angle", self._angle)
        self._form.addRow("Material", self._material)
        self._form.addRow("Section", self._section)
        self._form.addRow("Axial force", self._axial)
        self._form.addRow("Axial stress", self._stress)
        self._form.addRow("Elongation", self._elongation)

        self._end_forces_group = self._build_end_forces_group()
        layout.addWidget(self._end_forces_group)

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)  # close, not accept: the window is reusable
        layout.addWidget(buttons)

        self.show_member(member_id, result)

    # ------------------------------------------------------------------ setup

    def _value_label(self) -> QLabel:
        label = QLabel(MISSING)
        # Engineers copy these numbers into calculations; make them selectable.
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _build_end_forces_group(self) -> QGroupBox:
        group = QGroupBox("Local end forces")
        box = QVBoxLayout(group)

        caption = QLabel(
            "Forces the joints exert on the member, in member local axes (conventions "
            "section 5). Local x runs from joint i to joint j."
        )
        caption.setWordWrap(True)
        caption.setFrameShape(QFrame.Shape.NoFrame)
        box.addWidget(caption)

        self._end_forces = QTableWidget(len(END_FORCE_ROWS), 2)
        self._end_forces.setHorizontalHeaderLabels(["End i", "End j"])
        self._end_forces.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._end_forces.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._end_forces.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._end_forces.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        for row in range(len(END_FORCE_ROWS)):
            for column in range(2):
                self._end_forces.setItem(row, column, QTableWidgetItem(MISSING))
        box.addWidget(self._end_forces)
        return group

    # ------------------------------------------------------------------ display

    def show_member(self, member_id: int, result: AnalysisResult) -> None:
        """Retarget this dialog at another member, reusing the same window.

        Takes a fresh ``result`` as well as the id so that re-running the analysis and
        clicking a member are the same operation from the caller's point of view.
        """
        self._member_id = member_id
        self._result = result
        self.setWindowTitle(f"Member {member_id} details")
        self._heading.setText(f"Member {member_id}")

        member_result = result.members.get(member_id)
        self._show_geometry(member_id, member_result)
        self._show_properties(member_id)
        self._show_forces(member_result)
        self._show_end_forces(result.analysis_type, member_result)
        self.adjustSize()

    def _show_geometry(self, member_id: int, member_result: MemberResult | None) -> None:
        """Joint ids and coordinates from the model; length and angle from the result."""
        member = self.structure.members.get(member_id)
        if member is None:
            self._joints.setText(MISSING)
        else:
            self._joints.setText(
                f"{self._describe_node(member.node_i)}  to  {self._describe_node(member.node_j)}"
            )

        if member_result is None:
            self._length.setText(MISSING)
            self._angle.setText(MISSING)
            return
        self._length.setText(self.units.format_length(member_result.length))
        self._angle.setText(f"{member_result.angle_deg:.2f} deg")

    def _describe_node(self, node_id: int) -> str:
        node = self.structure.nodes.get(node_id)
        if node is None:
            return f"node {node_id} (missing)"
        x = self.units.length_from_si(node.x)
        y = self.units.length_from_si(node.y)
        return f"node {node_id} ({x:g}, {y:g}) {self.units.length}"

    def _show_properties(self, member_id: int) -> None:
        member = self.structure.members.get(member_id)
        if member is None:
            self._material.setText(MISSING)
            self._section.setText(MISSING)
            return

        material = self.structure.materials.get(member.material_id)
        if material is None:
            self._material.setText(f"material {member.material_id} (missing)")
        else:
            modulus = self.units.modulus_from_si(material.E)
            self._material.setText(f"{material.name}   E = {modulus:.6g} {self.units.modulus}")

        section = self.structure.sections.get(member.section_id)
        if section is None:
            self._section.setText(f"section {member.section_id} (missing)")
        else:
            area = self._area_from_si(section.area)
            self._section.setText(f"{section.name}   A = {area:.6g} {self.units.length}^2")

    def _area_from_si(self, area_si: float) -> float:
        """Areas have no dedicated converter; two length conversions is exactly one area one."""
        return self.units.length_from_si(self.units.length_from_si(area_si))

    def _show_forces(self, member_result: MemberResult | None) -> None:
        if member_result is None:
            self._badge.setText("No result")
            self._badge.setStyleSheet(
                BADGE_STYLE.format(fg=BADGE_COLOURS[MemberState.ZERO][0], bg="#f0f0f0")
            )
            self._axial.setText(MISSING)
            self._stress.setText(MISSING)
            self._elongation.setText(MISSING)
            return

        foreground, background = BADGE_COLOURS[member_result.state]
        self._badge.setText(member_result.state_label.upper())
        self._badge.setStyleSheet(BADGE_STYLE.format(fg=foreground, bg=background))

        self._axial.setText(
            f"{self._signed(member_result.axial, self.units.format_force(member_result.axial))}"
            "   (tension positive)"
        )

        stress = self.units.stress_from_si(member_result.stress)
        self._stress.setText(f"{stress:+.6g} {self.units.stress}")

        elongation = self.units.format_length(member_result.elongation, decimals=6)
        self._elongation.setText(
            f"{self._signed(member_result.elongation, elongation)}   (lengthening positive)"
        )

    @staticmethod
    def _signed(value: float, text: str) -> str:
        """``format_*`` only prints a minus sign; tension deserves an explicit plus."""
        return f"+{text}" if value > 0.0 else text

    def _show_end_forces(
        self, analysis_type: AnalysisType, member_result: MemberResult | None
    ) -> None:
        """Frame only.

        In truss mode the shear and moment slots are structurally zero-padded, not computed.
        Printing "0.000" there would advertise a result that does not exist, so the whole
        table is hidden instead (conventions section 3).
        """
        show = analysis_type is AnalysisType.FRAME and member_result is not None
        self._end_forces_group.setVisible(show)
        if not show or member_result is None:
            return

        forces = member_result.end_forces_local
        labels: list[str] = []
        for row, (name, index_i, index_j) in enumerate(END_FORCE_ROWS):
            is_moment = name.startswith("Moment")
            unit = self.units.moment_unit if is_moment else self.units.force
            labels.append(f"{name} ({unit})")
            for column, index in ((0, index_i), (1, index_j)):
                value = float(forces[index])
                display = (
                    self.units.moment_from_si(value)
                    if is_moment
                    else self.units.force_from_si(value)
                )
                item = self._end_forces.item(row, column)
                if item is not None:
                    item.setText(f"{display:+.3f}")
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
        self._end_forces.setVerticalHeaderLabels(labels)
        self._end_forces.setFixedHeight(
            self._end_forces.verticalHeader().length()
            + self._end_forces.horizontalHeader().height()
            + 2
        )


__all__ = ["MemberDetailDialog"]
