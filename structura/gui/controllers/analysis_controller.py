"""Runs the solver on behalf of the GUI and owns the current results.

The API is signal-based even though the solve is synchronous today. Models of the size this
application targets solve in milliseconds, so a worker thread would be complexity without
benefit right now - but callers that already listen for ``finished`` will not need changing
when one is added.

This is the only place the GUI touches the analysis engine. Nothing downstream computes a
force: the widgets read numbers out of ``AnalysisResult`` and format them.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ...core.analysis import AnalysisError, AnalysisResult, solve
from ...core.validation import Diagnostic
from ..document import Document


class AnalysisController(QObject):
    """Holds the latest analysis and tells the UI when it stops being trustworthy."""

    started = Signal()
    finished = Signal(object)
    """Emitted with the ``AnalysisResult`` on success."""

    failed = Signal(str, object)
    """Emitted with (message, list[Diagnostic]) when the model cannot be analysed."""

    stalenessChanged = Signal(bool)
    """Emitted when results start or stop describing the drawing on screen."""

    def __init__(self, document: Document, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self._result: AnalysisResult | None = None
        self._stale = False
        document.modelChanged.connect(self._recheck_staleness)

    # ------------------------------------------------------------------ state

    @property
    def result(self) -> AnalysisResult | None:
        return self._result

    @property
    def has_result(self) -> bool:
        return self._result is not None

    @property
    def is_stale(self) -> bool:
        """True when the model has been edited since these results were computed.

        Stale results must be visually distinguished rather than silently kept: numbers that
        describe a drawing the user has since changed are worse than no numbers at all.
        """
        return self._stale

    def _recheck_staleness(self) -> None:
        stale = self._result is not None and self._result.is_stale_for(
            self.document.structure.content_hash()
        )
        if stale != self._stale:
            self._stale = stale
            self.stalenessChanged.emit(stale)

    # ------------------------------------------------------------------ actions

    def run(self) -> AnalysisResult | None:
        """Analyse the active load case. Returns the result, or ``None`` on failure."""
        self.started.emit()
        try:
            result = solve(self.document.structure)
        except AnalysisError as error:
            self._result = None
            self._set_stale(False)
            self.failed.emit(str(error), list(error.diagnostics))
            return None

        self._result = result
        self._set_stale(False)
        self.finished.emit(result)
        return result

    def clear(self) -> None:
        """Discard the current results, as New and Open do."""
        if self._result is not None:
            self._result = None
            self._set_stale(False)

    def _set_stale(self, stale: bool) -> None:
        if stale != self._stale:
            self._stale = stale
            self.stalenessChanged.emit(stale)

    # ------------------------------------------------------------------ queries

    def diagnostics(self) -> list[Diagnostic]:
        """Warnings and notes from the last successful run."""
        return list(self._result.diagnostics) if self._result is not None else []
