"""Structura — 2D structural analysis and drawing application.

Layering rule enforced by ``tests/test_architecture.py``:

    structura.core   →  pure Python + NumPy/SciPy, ZERO GUI imports
    structura.gui    →  PySide6; may import core, never the other way round
"""

__version__ = "0.1.0"
