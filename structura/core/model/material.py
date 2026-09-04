"""Material and cross-section properties.

All values are SI base units: ``E`` in Pa, ``area`` in m^2, ``inertia`` in m^4.

For a *statically determinate* structure these properties do not affect member forces or
reactions at all — only displacements. For an indeterminate one they change everything. The
UI should say so, because it surprises people.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Material:
    """Linear elastic isotropic material."""

    id: int
    name: str = "Steel"
    E: float = 2.0e11
    """Young's modulus, Pa. Default 200 GPa (structural steel)."""
    nu: float = 0.3
    """Poisson's ratio. Unused by the 2D formulation; kept for reporting and future use."""
    rho: float = 7850.0
    """Density, kg/m^3. Used only by the optional self-weight load."""

    def __post_init__(self) -> None:
        if self.E <= 0.0:
            raise ValueError(f"Material {self.id}: E must be positive, got {self.E}")
        if self.rho < 0.0:
            raise ValueError(f"Material {self.id}: density must be non-negative, got {self.rho}")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "E": self.E, "nu": self.nu, "rho": self.rho}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Material:
        return cls(
            id=int(data["id"]),
            name=str(data.get("name", "Steel")),
            E=float(data.get("E", 2.0e11)),
            nu=float(data.get("nu", 0.3)),
            rho=float(data.get("rho", 7850.0)),
        )


@dataclass(slots=True)
class Section:
    """Cross-section properties."""

    id: int
    name: str = "Default"
    area: float = 1.0e-3
    """Cross-sectional area A, m^2. Default 1000 mm^2."""
    inertia: float = 1.0e-6
    """Second moment of area I about the bending axis, m^4. Default 1e6 mm^4."""
    depth: float = 0.0
    """Optional section depth, m. Presentation and stress reporting only."""

    def __post_init__(self) -> None:
        if self.area <= 0.0:
            raise ValueError(f"Section {self.id}: area must be positive, got {self.area}")
        if self.inertia <= 0.0:
            raise ValueError(f"Section {self.id}: inertia must be positive, got {self.inertia}")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "A": self.area,
            "I": self.inertia,
        }
        if self.depth:
            data["depth"] = self.depth
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Section:
        return cls(
            id=int(data["id"]),
            name=str(data.get("name", "Default")),
            area=float(data.get("A", 1.0e-3)),
            inertia=float(data.get("I", 1.0e-6)),
            depth=float(data.get("depth", 0.0)),
        )
