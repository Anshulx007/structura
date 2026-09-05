"""Display-unit handling.

The solver only ever sees SI base units (N, m, Pa, rad) — see ``docs/conventions.md`` §1.
This module is the *only* place where conversion happens, and it is used exclusively at the
GUI and file-import boundary. Nothing in ``structura.core.analysis`` may import it.

Every factor below answers: "how many SI base units is one of this unit?"
So ``value_si = value_display * factor`` and ``value_display = value_si / factor``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LENGTH_FACTORS: dict[str, float] = {
    "m": 1.0,
    "mm": 1.0e-3,
    "cm": 1.0e-2,
    "ft": 0.3048,
    "in": 0.0254,
}

FORCE_FACTORS: dict[str, float] = {
    "N": 1.0,
    "kN": 1.0e3,
    "MN": 1.0e6,
    "kgf": 9.80665,
    "lbf": 4.4482216152605,
    "kip": 4448.2216152605,
}

STRESS_FACTORS: dict[str, float] = {
    "Pa": 1.0,
    "kPa": 1.0e3,
    "MPa": 1.0e6,
    "GPa": 1.0e9,
    "N/mm2": 1.0e6,
    "psi": 6894.757293168361,
    "ksi": 6894757.293168361,
}


@dataclass(frozen=True, slots=True)
class UnitSystem:
    """A set of display units. Defaults are the usual civil-engineering choices.

    ``moment`` and ``distributed load`` units are derived from ``force`` and ``length`` so
    they can never disagree with them.
    """

    length: str = "m"
    force: str = "kN"
    stress: str = "MPa"
    """Unit for computed stresses. Engineers read member stress in MPa, not GPa."""
    modulus: str = "GPa"
    """Unit for elastic modulus. Same dimension as stress, but conventionally reported in GPa.

    Kept separate deliberately: sharing one field makes either E read as 200000 MPa or a member
    stress read as -0.0125 GPa, and both are unreadable in the place they actually appear.
    """
    angle_in_degrees: bool = True

    def __post_init__(self) -> None:
        if self.length not in LENGTH_FACTORS:
            raise ValueError(f"Unknown length unit {self.length!r}")
        if self.force not in FORCE_FACTORS:
            raise ValueError(f"Unknown force unit {self.force!r}")
        if self.stress not in STRESS_FACTORS:
            raise ValueError(f"Unknown stress unit {self.stress!r}")
        if self.modulus not in STRESS_FACTORS:
            raise ValueError(f"Unknown modulus unit {self.modulus!r}")

    # -- factors -------------------------------------------------------------

    @property
    def length_factor(self) -> float:
        return LENGTH_FACTORS[self.length]

    @property
    def force_factor(self) -> float:
        return FORCE_FACTORS[self.force]

    @property
    def stress_factor(self) -> float:
        return STRESS_FACTORS[self.stress]

    @property
    def modulus_factor(self) -> float:
        return STRESS_FACTORS[self.modulus]

    @property
    def moment_factor(self) -> float:
        return self.force_factor * self.length_factor

    @property
    def distributed_factor(self) -> float:
        """Factor for a load intensity (force per unit length)."""
        return self.force_factor / self.length_factor

    @property
    def moment_unit(self) -> str:
        return f"{self.force}.{self.length}"

    @property
    def distributed_unit(self) -> str:
        return f"{self.force}/{self.length}"

    # -- conversion ----------------------------------------------------------

    def length_to_si(self, value: float) -> float:
        return value * self.length_factor

    def length_from_si(self, value: float) -> float:
        return value / self.length_factor

    def force_to_si(self, value: float) -> float:
        return value * self.force_factor

    def force_from_si(self, value: float) -> float:
        return value / self.force_factor

    def moment_to_si(self, value: float) -> float:
        return value * self.moment_factor

    def moment_from_si(self, value: float) -> float:
        return value / self.moment_factor

    def distributed_to_si(self, value: float) -> float:
        return value * self.distributed_factor

    def distributed_from_si(self, value: float) -> float:
        return value / self.distributed_factor

    def stress_to_si(self, value: float) -> float:
        return value * self.stress_factor

    def stress_from_si(self, value: float) -> float:
        return value / self.stress_factor

    def modulus_to_si(self, value: float) -> float:
        return value * self.modulus_factor

    def modulus_from_si(self, value: float) -> float:
        return value / self.modulus_factor

    def angle_from_si(self, radians: float) -> float:
        return math.degrees(radians) if self.angle_in_degrees else radians

    def angle_to_si(self, value: float) -> float:
        return math.radians(value) if self.angle_in_degrees else value

    # -- formatting ----------------------------------------------------------

    def format_force(self, value_si: float, decimals: int = 3) -> str:
        return f"{self.force_from_si(value_si):.{decimals}f} {self.force}"

    def format_moment(self, value_si: float, decimals: int = 3) -> str:
        return f"{self.moment_from_si(value_si):.{decimals}f} {self.moment_unit}"

    def format_length(self, value_si: float, decimals: int = 3) -> str:
        return f"{self.length_from_si(value_si):.{decimals}f} {self.length}"

    def to_dict(self) -> dict[str, str]:
        """Serialise for the ``display_units`` block of a ``.stru`` file."""
        return {
            "length": self.length,
            "force": self.force,
            "moment": self.moment_unit,
            "stress": self.stress,
            "modulus": self.modulus,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> UnitSystem:
        """Rebuild from a ``display_units`` block. ``moment`` is derived, so it is ignored."""
        return cls(
            length=data.get("length", "m"),
            force=data.get("force", "kN"),
            stress=data.get("stress", "MPa"),
            modulus=data.get("modulus", "GPa"),
        )


SI = UnitSystem(length="m", force="N", stress="Pa", modulus="Pa")
"""The solver's own unit system — the identity conversion. Useful in tests."""

DEFAULT = UnitSystem()
"""What the GUI starts with: metres, kilonewtons, MPa stress, GPa modulus."""
