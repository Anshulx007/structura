"""The open project: a ``Structure``, its undo stack, and where it came from.

Every mutation the user makes goes through ``QUndoCommand`` objects pushed onto this stack.
Nothing else is allowed to touch ``document.structure`` - that single rule is what makes
undo/redo trustworthy instead of a feature that mostly works.

Selection deliberately does **not** live here. ``QGraphicsScene`` already implements
selection, rubber-banding and ctrl-click correctly; mirroring it into a second source of truth
would only create two things to keep in sync.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..core import io
from ..core.model import Structure

UNDO_LIMIT = 200
"""Plenty for a drawing session, and bounded so a long session cannot grow without limit."""


class Document(QObject):
    """One open project."""

    modelChanged = Signal()
    """The structure was altered. The canvas and panels re-read the model."""

    fileChanged = Signal()
    """The file path or the modified flag changed. The window title re-reads them."""

    def __init__(self, structure: Structure | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._structure = structure if structure is not None else Structure()
        self._path: Path | None = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)

    def _on_clean_changed(self, _clean: bool) -> None:
        self.fileChanged.emit()

    # ------------------------------------------------------------------ state

    @property
    def structure(self) -> Structure:
        return self._structure

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def is_modified(self) -> bool:
        """True when there are unsaved changes. Driven by the undo stack's clean marker."""
        return not self.undo_stack.isClean()

    @property
    def display_name(self) -> str:
        """What the title bar shows. ASCII only."""
        base = self._path.name if self._path is not None else "Untitled"
        return base + "*" if self.is_modified else base

    # ------------------------------------------------------------------ mutation

    def push(self, command: QUndoCommand) -> None:
        """Apply a command. This is the only supported way to change the model."""
        self.undo_stack.push(command)

    def touch(self) -> None:
        """Announce that the structure changed. Commands call this; nothing else should."""
        self.modelChanged.emit()

    # ------------------------------------------------------------------ files

    def reset(self, structure: Structure | None = None, path: Path | None = None) -> None:
        """Replace the whole document, as New and Open do.

        Clearing the undo stack is deliberate: undoing across a file load would leave the
        drawing and the file path describing different projects.
        """
        self._structure = structure if structure is not None else Structure()
        self._path = path
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.modelChanged.emit()
        self.fileChanged.emit()

    def load(self, path: str | Path) -> None:
        """Open a project file, replacing the current document."""
        target = Path(path)
        self.reset(io.load(target), target)

    def save(self, path: str | Path | None = None) -> Path:
        """Write the project. Marks the undo stack clean so the modified flag clears."""
        target = Path(path) if path is not None else self._path
        if target is None:
            raise ValueError("No path given and this document has never been saved.")
        written = io.save(self._structure, target)
        self._path = written
        self.undo_stack.setClean()
        self.fileChanged.emit()
        return written
