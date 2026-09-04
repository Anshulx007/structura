"""Make the project importable however pytest is invoked, and run Qt headless.

``QT_QPA_PLATFORM=offscreen`` must be set before the first ``QApplication`` is constructed.
pytest-qt builds one lazily on first use of the ``qtbot`` / ``qapp`` fixtures, so setting it
here at collection time is early enough and keeps the suite runnable on a machine with no
display (CI, or a terminal-only session).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HAVE_PYSIDE6 = importlib.util.find_spec("PySide6") is not None

requires_qt = pytest.mark.skipif(
    not HAVE_PYSIDE6,
    reason="PySide6 is not installed; GUI tests are optional (pip install -e '.[gui]')",
)
"""Decorator for tests that need Qt.

The core test suite must stay runnable without any GUI toolkit installed - that is the whole
point of the layering - so GUI tests skip rather than fail when PySide6 is absent.
"""
