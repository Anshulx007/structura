"""Shared NumPy type aliases.

Bare ``np.ndarray`` says nothing about element type, which matters in a numerical core: an
integer index array and a float stiffness matrix are not interchangeable, and mypy should say
so. These aliases keep the annotations honest without repeating the generic parameters
everywhere.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
"""Displacements, forces, stiffness matrices — anything carrying physical quantities."""

IntArray = npt.NDArray[np.int_]
"""DOF index arrays and partitions."""

BoolArray = npt.NDArray[np.bool_]
"""Restraint masks."""

__all__ = ["BoolArray", "FloatArray", "IntArray"]
