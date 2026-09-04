"""Joint / node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Node:
    """A joint in the structure.

    Coordinates are in metres with **+Y up** (conventions §2). ``id`` is stable for the life
    of the model and is never reused after deletion, because analysis results are keyed by it.
    """

    id: int
    x: float
    y: float
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "x": self.x, "y": self.y}
        if self.label:
            data["label"] = self.label
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        return cls(
            id=int(data["id"]),
            x=float(data["x"]),
            y=float(data["y"]),
            label=str(data.get("label", "")),
        )
