from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class FitDataPoint:
    """One row of the Fit-to-data table: a measured beam diameter at a given
    z location. Either field may be blank (None) while the user is still
    filling in the row."""

    z_mm: Optional[float] = None
    diameter_mm: Optional[float] = None

    def is_valid(self) -> bool:
        return self.z_mm is not None and self.diameter_mm is not None and self.diameter_mm > 0

    def to_dict(self) -> Dict[str, Any]:
        return {"z_mm": self.z_mm, "diameter_mm": self.diameter_mm}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FitDataPoint":
        return cls(z_mm=d.get("z_mm"), diameter_mm=d.get("diameter_mm"))
