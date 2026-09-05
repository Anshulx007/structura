"""Dialog for entering a joint load.

Lives here rather than inside ``LoadTool`` so the tool stays drivable from a test without a
modal window appearing. The main window injects ``LoadDialog.prompt`` as the tool's callable.

Values are entered in display units and returned in SI base units, because the model stores SI
and only this layer is allowed to convert (conventions section 1).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.model import NodalLoad
from ...core.units import UnitSystem

RANGE = 1.0e9
DECIMALS = 4


class LoadDialog(QDialog):
    """Asks for the force and moment at one joint."""

    def __init__(
        self, load: NodalLoad, units: UnitSystem, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Load at node {load.node_id}")
        self._units = units
        self._node_id = load.node_id

        layout = QVBoxLayout(self)
        note = QLabel(
            "Positive X is to the right, positive Y is up, positive moment is\n"
            "counter-clockwise. A downward load is a negative Fy."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self._fx = self._spin(units.force_from_si(load.fx))
        self._fy = self._spin(units.force_from_si(load.fy))
        self._mz = self._spin(units.moment_from_si(load.mz))
        form.addRow(f"Fx ({units.force})", self._fx)
        form.addRow(f"Fy ({units.force})", self._fy)
        form.addRow(f"Mz ({units.moment_unit})", self._mz)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-RANGE, RANGE)
        spin.setDecimals(DECIMALS)
        spin.setValue(value)
        return spin

    def result_load(self) -> NodalLoad:
        """The entered values, converted back to SI base units."""
        return NodalLoad(
            self._node_id,
            fx=self._units.force_to_si(self._fx.value()),
            fy=self._units.force_to_si(self._fy.value()),
            mz=self._units.moment_to_si(self._mz.value()),
        )

    @classmethod
    def prompt(
        cls, load: NodalLoad, units: UnitSystem, parent: QWidget | None = None
    ) -> NodalLoad | None:
        """Show the dialog. Returns ``None`` when the user cancels, which the tool honours."""
        dialog = cls(load, units, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_load()
        return None


__all__ = ["LoadDialog"]
