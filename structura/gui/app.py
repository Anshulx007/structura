"""Application entry point.

    python -m structura.gui.app [project.stru]

Qt is imported inside ``main`` so that a missing or broken PySide6 produces an explanation
rather than a traceback from an import at module scope. On Windows that failure is common
enough to be worth naming: Anaconda ships an older MSVC runtime next to ``python.exe``, and
because Windows searches the executable's own directory first, it shadows both the system copy
and the newer one PySide6 bundles. Recent Qt builds then fail to load with WinError 127.

All output here is ASCII: a cp1252 console mangles anything else, and this is exactly the
moment a user needs to be able to read the message.
"""

from __future__ import annotations

import sys
from pathlib import Path

QT_IMPORT_HELP = """\
Structura could not start because the Qt bindings (PySide6) failed to load.

  {error}

Install them with:
    pip install -e ".[gui]"

If PySide6 is installed and this still happens on Windows with Anaconda, the cause is
usually a Microsoft Visual C++ runtime conflict: Anaconda ships msvcp140.dll next to
python.exe, and Windows loads that in preference to the newer copy Qt needs. Pinning a
slightly older Qt avoids it:
    pip install "PySide6==6.8.1.1"

The analysis engine does not need Qt at all. To use it without a window:
    python -m structura.core.cli solve T2
"""


def main(argv: list[str] | None = None) -> int:
    """Start the GUI. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as error:  # pragma: no cover - environment dependent
        print(QT_IMPORT_HELP.format(error=error), file=sys.stderr)
        return 1

    from .main_window import MainWindow

    app = QApplication(args)
    app.setApplicationName("Structura")
    app.setOrganizationName("Structura")

    window = MainWindow()

    positional = [a for a in args if not a.startswith("-")]
    if positional:
        target = Path(positional[0])
        if target.exists():
            window.load_path(target)
        else:
            print(f"Project file not found: {target}", file=sys.stderr)

    window.show()
    window.view.fit_to_model()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
