from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class InputBeamSpec:
    """Describes the input beam as measured at some plane z_ref, which need
    not be the beam's waist. `collimated=True` means the wavefront is flat
    (R=inf) at z_ref -- i.e. z_ref is the waist. Otherwise `r_ref` gives the
    measured wavefront radius of curvature there."""

    wavelength_nm: float = 632.8  # HeNe default
    z_ref: float = 0.0  # mm
    w_ref: float = 0.5  # mm, 1/e^2 radius at z_ref
    collimated: bool = True
    r_ref: Optional[float] = None  # mm, wavefront ROC at z_ref when not collimated
    x_offset: float = 0.0  # mm, transverse offset of the beam axis

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wavelength_nm": self.wavelength_nm,
            "z_ref": self.z_ref,
            "w_ref": self.w_ref,
            "collimated": self.collimated,
            "r_ref": self.r_ref,
            "x_offset": self.x_offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InputBeamSpec":
        return cls(
            wavelength_nm=d.get("wavelength_nm", 632.8),
            z_ref=d.get("z_ref", 0.0),
            w_ref=d.get("w_ref", 0.5),
            collimated=d.get("collimated", True),
            r_ref=d.get("r_ref"),
            x_offset=d.get("x_offset", 0.0),
        )
